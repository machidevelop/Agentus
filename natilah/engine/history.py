"""Historical pattern index.

Agents need to know whether a signal is a one-off accident or a recurring
habit of a user or a job family. Recurrence is measured from the ingested
trace only; nothing here is inferred by an LLM.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean

from natilah.models.domain import ClusterDataset, Job, Observation
from natilah.models.enums import OpportunityType

_DIGITS = re.compile(r"[0-9]+")
_UUIDISH = re.compile(r"[0-9a-f]{8,}", re.IGNORECASE)


def job_family(job: Job) -> str:
    """Collapse a job name to its family: ml-train-047 becomes ml-train-#."""
    name = _UUIDISH.sub("#", job.name or job.job_id)
    name = _DIGITS.sub("#", name)
    return name.strip("-_ .") or "unnamed"


@dataclass
class JobProfile:
    job_id: str
    user: str
    family: str
    requested_gpus: int
    allocated_gpus: int
    runtime_hours: float
    wait_seconds: float
    mean_utilization: float
    active_gpus: int
    idle_gpu_hours: float


@dataclass
class FamilyStats:
    key: str
    jobs: int = 0
    mean_utilization: float = 0.0
    mean_allocated_gpus: float = 0.0
    mean_wait_seconds: float = 0.0
    idle_gpu_hours: float = 0.0
    signal_counts: dict[str, int] = field(default_factory=dict)


class HistoricalPatternIndex:
    """Read-only aggregate view over the ingested window.

    Two axes are indexed because they answer different questions. Job family
    answers whether a workload always over-requests; user answers whether the
    pattern is a person-level habit.
    """

    ACTIVE_THRESHOLD_PCT = 40.0
    IDLE_THRESHOLD_PCT = 5.0

    def __init__(self, dataset: ClusterDataset):
        self.dataset = dataset
        self.profiles: dict[str, JobProfile] = {}
        self.by_family: dict[str, FamilyStats] = {}
        self.by_user: dict[str, FamilyStats] = {}
        self._build()

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        samples_by_job = self.dataset.samples_by_job()
        alloc_by_job = self.dataset.allocation_by_job()

        for job in self.dataset.jobs:
            alloc = alloc_by_job.get(job.job_id)
            allocated = len(alloc.gpu_ids) if alloc else job.requested_gpus
            runtime_h = 0.0
            if job.start_time and job.end_time:
                runtime_h = (job.end_time - job.start_time).total_seconds() / 3600.0
            elif alloc and alloc.end_time:
                runtime_h = (alloc.end_time - alloc.start_time).total_seconds() / 3600.0
            wait = 0.0
            if job.start_time and job.submit_time:
                wait = max(0.0, (job.start_time - job.submit_time).total_seconds())

            per_gpu: dict[str, list[float]] = defaultdict(list)
            for sample in samples_by_job.get(job.job_id, []):
                per_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
            gpu_means = {gid: mean(vals) for gid, vals in per_gpu.items() if vals}
            util = mean(gpu_means.values()) if gpu_means else 0.0
            active = sum(1 for v in gpu_means.values() if v > self.ACTIVE_THRESHOLD_PCT)
            idle_gpus = sum(1 for v in gpu_means.values() if v < self.IDLE_THRESHOLD_PCT)

            profile = JobProfile(
                job_id=job.job_id,
                user=job.user,
                family=job_family(job),
                requested_gpus=job.requested_gpus,
                allocated_gpus=allocated,
                runtime_hours=runtime_h,
                wait_seconds=wait,
                mean_utilization=util,
                active_gpus=active,
                idle_gpu_hours=idle_gpus * runtime_h,
            )
            self.profiles[job.job_id] = profile
            self._accumulate(self.by_family, profile.family, profile)
            self._accumulate(self.by_user, profile.user, profile)

    @staticmethod
    def _accumulate(bucket: dict[str, FamilyStats], key: str, profile: JobProfile) -> None:
        stats = bucket.setdefault(key, FamilyStats(key=key))
        n = stats.jobs
        stats.mean_utilization = (stats.mean_utilization * n + profile.mean_utilization) / (n + 1)
        stats.mean_allocated_gpus = (stats.mean_allocated_gpus * n + profile.allocated_gpus) / (n + 1)
        stats.mean_wait_seconds = (stats.mean_wait_seconds * n + profile.wait_seconds) / (n + 1)
        stats.idle_gpu_hours += profile.idle_gpu_hours
        stats.jobs = n + 1

    # ------------------------------------------------------------- signal log

    def register_observations(self, observations: list[Observation]) -> None:
        """Record which families and users produced which signals in this window."""
        for obs in observations:
            for job_id in obs.affected_job_ids or [obs.decision.job_id]:
                profile = self.profiles.get(job_id)
                if profile is None:
                    continue
                for bucket, key in (
                    (self.by_family, profile.family),
                    (self.by_user, profile.user),
                ):
                    stats = bucket.get(key)
                    if stats is None:
                        continue
                    name = obs.signal_type.value
                    stats.signal_counts[name] = stats.signal_counts.get(name, 0) + 1

    # ---------------------------------------------------------------- queries

    def profile_for(self, job_id: str) -> JobProfile | None:
        return self.profiles.get(job_id)

    def recurrence(self, job_id: str, signal_type: OpportunityType) -> int:
        """Times this signal appeared in the same job family, excluding this one."""
        profile = self.profiles.get(job_id)
        if profile is None:
            return 0
        stats = self.by_family.get(profile.family)
        if stats is None:
            return 0
        return max(0, stats.signal_counts.get(signal_type.value, 0) - 1)

    def evidence(self, job_id: str, signal_type: OpportunityType) -> dict:
        profile = self.profiles.get(job_id)
        if profile is None:
            return {"available": False}
        family = self.by_family.get(profile.family, FamilyStats(key=profile.family))
        user = self.by_user.get(profile.user, FamilyStats(key=profile.user))
        return {
            "available": True,
            "job_family": profile.family,
            "family_jobs_in_window": family.jobs,
            "family_mean_utilization_pct": round(family.mean_utilization, 2),
            "family_mean_allocated_gpus": round(family.mean_allocated_gpus, 2),
            "family_idle_gpu_hours": round(family.idle_gpu_hours, 2),
            "family_signal_counts": dict(family.signal_counts),
            "user": profile.user,
            "user_jobs_in_window": user.jobs,
            "user_mean_utilization_pct": round(user.mean_utilization, 2),
            "user_mean_wait_seconds": round(user.mean_wait_seconds, 1),
            "this_job_mean_utilization_pct": round(profile.mean_utilization, 2),
            "this_job_wait_seconds": round(profile.wait_seconds, 1),
            "wait_vs_user_mean": (
                round(profile.wait_seconds / user.mean_wait_seconds, 2)
                if user.mean_wait_seconds > 0
                else None
            ),
            "signal_recurrence_in_family": self.recurrence(job_id, signal_type),
        }
