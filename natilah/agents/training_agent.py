"""Training-efficiency agent.

Objective: GPU-hours burned by training overhead that bought nothing.

Four conditions, four ways a training run wastes GPU time without producing
useful gradient steps:

    dataloader stalls   GPUs sit idle waiting for the next batch because the
                        data pipeline cannot keep up with the accelerator
    restart waste       a run crashes and replays work from scratch because no
                        checkpoint was available to resume from
    non-converging      a hyperparameter sweep keeps launching runs that fail
    sweeps              or diverge, burning GPU-hours on configurations that
                        never had a chance
    checkpoint          excessive checkpoint frequency turns productive GPU
    overhead            time into I/O — writing state that will never be read

Each condition claims GPU-hours, because that is what the training run held
while doing nothing useful. The claim is conservative: it counts only the
fraction of the run clearly attributable to the overhead, not the whole run.
"""

from __future__ import annotations

from collections import defaultdict

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.domain import (
    ClusterDataset,
    ResourceClaim,
    ResourceInterval,
)
from natilah.models.enums import AgentObjective, Meter, OpportunityType
from natilah.models.resources import TrainingRun

MIN_WALL_HOURS = 0.1
MIN_STALL_FRACTION = 0.05
MIN_CHECKPOINT_FRACTION = 0.10
MIN_SWEEP_FAILURE_RATIO = 0.50
MIN_SWEEP_RUNS = 3
RESTART_REPLAY_FRACTION = 0.30
FAILED_EXIT_REASONS = frozenset({"failed", "diverged", "killed"})


class TrainingEfficiencyAgent(ResourceAgent):
    name = "training_efficiency_agent"
    objective = AgentObjective.TRAINING_EFFICIENCY
    primary_meter = Meter.GPU_HOURS
    signal_types = (
        OpportunityType.DATALOADER_STALL,
        OpportunityType.RESTART_WASTE,
        OpportunityType.NONCONVERGING_SWEEP,
        OpportunityType.CHECKPOINT_OVERHEAD,
    )
    finding_title = "Training efficiency waste"

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        return [
            *self._detect_stalls(dataset),
            *self._detect_restart_waste(dataset),
            *self._detect_nonconverging_sweeps(dataset),
            *self._detect_checkpoint_overhead(dataset),
        ]

    def _detect_stalls(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for run in dataset.training_runs:
            if run.wall_hours < MIN_WALL_HOURS or run.end is None:
                continue
            wall_seconds = run.wall_hours * 3600.0
            fraction = run.dataloader_stall_seconds / wall_seconds if wall_seconds > 0 else 0.0
            if fraction < MIN_STALL_FRACTION:
                continue
            wasted_gpu_hours = run.dataloader_stall_seconds * run.gpu_count / 3600.0
            observations.append(
                ResourceObservation(
                    observation_id=f"dataloader_stall:{run.run_id}",
                    signal_type=OpportunityType.DATALOADER_STALL,
                    resource_id=run.run_id,
                    timestamp=run.start,
                    severity=round(min(1.0, fraction / 0.3), 4),
                    description=(
                        f"Run {run.run_id} spent {fraction:.0%} of its {run.wall_hours:.1f}h wall "
                        f"time ({run.dataloader_stall_seconds:.0f}s) stalled on the dataloader "
                        f"across {run.gpu_count} GPU(s), wasting {wasted_gpu_hours:.1f} GPU-h."
                    ),
                    affected_job_ids=[run.job_id] if run.job_id else [],
                    evidence={
                        "run_id": run.run_id,
                        "stall_seconds": run.dataloader_stall_seconds,
                        "stall_fraction": round(fraction, 4),
                        "wall_hours": round(run.wall_hours, 4),
                        "gpu_count": run.gpu_count,
                        "gpu_type": run.gpu_type,
                        "wasted_gpu_hours": round(wasted_gpu_hours, 4),
                        "signal_reason": (
                            f"{fraction:.0%} of wall time spent in dataloader stalls"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, fraction / 0.2), 4),
                    recurrence=0,
                )
            )
        return observations

    def _detect_restart_waste(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for run in dataset.training_runs:
            if run.wall_hours < MIN_WALL_HOURS or run.end is None:
                continue
            if run.restart_count <= 0 or run.resumed_from_checkpoint:
                continue
            wasted_hours = (
                run.restart_count / (run.restart_count + 1)
            ) * run.wall_hours * RESTART_REPLAY_FRACTION
            wasted_gpu_hours = wasted_hours * run.gpu_count
            observations.append(
                ResourceObservation(
                    observation_id=f"restart_waste:{run.run_id}",
                    signal_type=OpportunityType.RESTART_WASTE,
                    resource_id=run.run_id,
                    timestamp=run.start,
                    severity=round(min(1.0, run.restart_count / 5.0), 4),
                    description=(
                        f"Run {run.run_id} restarted {run.restart_count} time(s) without "
                        f"checkpoint resumption over {run.wall_hours:.1f}h on {run.gpu_count} "
                        f"GPU(s), replaying an estimated {wasted_gpu_hours:.1f} GPU-h of work."
                    ),
                    affected_job_ids=[run.job_id] if run.job_id else [],
                    evidence={
                        "run_id": run.run_id,
                        "restart_count": run.restart_count,
                        "resumed_from_checkpoint": False,
                        "wall_hours": round(run.wall_hours, 4),
                        "gpu_count": run.gpu_count,
                        "gpu_type": run.gpu_type,
                        "wasted_gpu_hours": round(wasted_gpu_hours, 4),
                        "replay_fraction": RESTART_REPLAY_FRACTION,
                        "signal_reason": (
                            f"{run.restart_count} restart(s) without checkpoint resumption"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, run.restart_count / 3.0), 4),
                    recurrence=0,
                )
            )
        return observations

    def _detect_nonconverging_sweeps(
        self, dataset: ClusterDataset
    ) -> list[ResourceObservation]:
        sweeps: dict[str, list[TrainingRun]] = defaultdict(list)
        for run in dataset.training_runs:
            if run.sweep_id:
                sweeps[run.sweep_id].append(run)

        observations: list[ResourceObservation] = []
        for sweep_id, runs in sweeps.items():
            if len(runs) < MIN_SWEEP_RUNS:
                continue
            failed = [
                r for r in runs
                if r.exit_reason in FAILED_EXIT_REASONS or r.best_metric is None
            ]
            ratio = len(failed) / len(runs)
            if ratio < MIN_SWEEP_FAILURE_RATIO:
                continue
            wasted_gpu_hours = sum(r.wall_hours * r.gpu_count for r in failed)
            earliest = min(r.start for r in runs)
            all_job_ids = [r.job_id for r in failed if r.job_id]
            observations.append(
                ResourceObservation(
                    observation_id=f"nonconverging_sweep:{sweep_id}",
                    signal_type=OpportunityType.NONCONVERGING_SWEEP,
                    resource_id=sweep_id,
                    timestamp=earliest,
                    severity=round(min(1.0, ratio), 4),
                    description=(
                        f"Sweep {sweep_id} has {len(failed)}/{len(runs)} runs "
                        f"({ratio:.0%}) that failed or never converged, burning "
                        f"{wasted_gpu_hours:.1f} GPU-h across those runs."
                    ),
                    affected_job_ids=all_job_ids,
                    evidence={
                        "sweep_id": sweep_id,
                        "total_runs": len(runs),
                        "failed_runs": len(failed),
                        "failure_ratio": round(ratio, 4),
                        "wasted_gpu_hours": round(wasted_gpu_hours, 4),
                        "failed_run_ids": [r.run_id for r in failed],
                        "signal_reason": (
                            f"{ratio:.0%} of sweep runs failed or never converged"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, ratio / 0.5), 4),
                    recurrence=max(0, len(failed) - 1),
                )
            )
        return observations

    def _detect_checkpoint_overhead(
        self, dataset: ClusterDataset
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for run in dataset.training_runs:
            if run.wall_hours < MIN_WALL_HOURS or run.end is None:
                continue
            wall_seconds = run.wall_hours * 3600.0
            fraction = run.checkpoint_seconds / wall_seconds if wall_seconds > 0 else 0.0
            if fraction < MIN_CHECKPOINT_FRACTION:
                continue
            excess_seconds = run.checkpoint_seconds - (wall_seconds * MIN_CHECKPOINT_FRACTION)
            wasted_gpu_hours = max(0.0, excess_seconds) * run.gpu_count / 3600.0
            observations.append(
                ResourceObservation(
                    observation_id=f"checkpoint_overhead:{run.run_id}",
                    signal_type=OpportunityType.CHECKPOINT_OVERHEAD,
                    resource_id=run.run_id,
                    timestamp=run.start,
                    severity=round(min(1.0, fraction / 0.3), 4),
                    description=(
                        f"Run {run.run_id} spent {fraction:.0%} of its {run.wall_hours:.1f}h "
                        f"wall time ({run.checkpoint_seconds:.0f}s) writing checkpoints across "
                        f"{run.gpu_count} GPU(s), wasting {wasted_gpu_hours:.1f} GPU-h above "
                        f"the {MIN_CHECKPOINT_FRACTION:.0%} baseline."
                    ),
                    affected_job_ids=[run.job_id] if run.job_id else [],
                    evidence={
                        "run_id": run.run_id,
                        "checkpoint_seconds": run.checkpoint_seconds,
                        "checkpoint_fraction": round(fraction, 4),
                        "wall_hours": round(run.wall_hours, 4),
                        "gpu_count": run.gpu_count,
                        "gpu_type": run.gpu_type,
                        "wasted_gpu_hours": round(wasted_gpu_hours, 4),
                        "signal_reason": (
                            f"{fraction:.0%} of wall time spent writing checkpoints"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, fraction / 0.15), 4),
                    recurrence=0,
                )
            )
        return observations

    # -------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.DATALOADER_STALL:
            return self._stall_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.RESTART_WASTE:
            return self._restart_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.NONCONVERGING_SWEEP:
            return self._sweep_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.CHECKPOINT_OVERHEAD:
            return self._checkpoint_candidates(dataset, observation)
        return []

    def _stall_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        run = self._find_run(dataset, str(ev.get("run_id", "")))
        if run is None or run.end is None:
            return []
        wasted = float(ev.get("wasted_gpu_hours", 0.0))
        rate = self.gpu_rate(run.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="optimize_dataloader",
                description=(
                    f"Optimize the dataloader for run {run.run_id}: increase prefetch depth, "
                    f"add workers, or pin memory to eliminate {wasted:.1f} GPU-h of stalls."
                ),
                proposed_action={
                    "kind": "optimize_dataloader",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "recovered_gpu_hours": round(wasted, 4),
                },
                rationale=(
                    "Dataloader stalls are idle GPU time caused by a CPU-bound or I/O-bound "
                    "data pipeline that cannot feed the accelerator fast enough."
                ),
                source="detector:stall:optimize_dataloader",
                claim=self._gpu_claim(run, wasted),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="faster_storage",
                description=(
                    f"Move training data to faster storage (NVMe or local SSD) for run "
                    f"{run.run_id} to reduce I/O-bound stalls."
                ),
                proposed_action={
                    "kind": "faster_storage",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "recovered_gpu_hours": round(wasted * 0.7, 4),
                },
                rationale=(
                    "When stalls are I/O-bound rather than CPU-bound, moving data closer to "
                    "the compute node recovers most of the idle time."
                ),
                source="detector:stall:faster_storage",
                claim=self._gpu_claim(run, wasted * 0.7),
                gpu_rate=rate,
            )
        )
        return candidates

    def _restart_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        run = self._find_run(dataset, str(ev.get("run_id", "")))
        if run is None or run.end is None:
            return []
        wasted = float(ev.get("wasted_gpu_hours", 0.0))
        rate = self.gpu_rate(run.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="enable_checkpoint_resumption",
                description=(
                    f"Enable checkpoint-based resumption for run {run.run_id} so restarts "
                    f"replay from the last checkpoint instead of from scratch, recovering "
                    f"{wasted:.1f} GPU-h."
                ),
                proposed_action={
                    "kind": "enable_checkpoint_resumption",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "restart_count": run.restart_count,
                    "recovered_gpu_hours": round(wasted, 4),
                },
                rationale=(
                    "Without checkpoint resumption, each restart replays all training from "
                    "step zero — a pure waste of GPU time proportional to restarts."
                ),
                source="detector:restart:checkpoint_resume",
                claim=self._gpu_claim(run, wasted),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="elastic_training",
                description=(
                    f"Use elastic training for run {run.run_id} to survive node failures "
                    f"without a full restart."
                ),
                proposed_action={
                    "kind": "elastic_training",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "recovered_gpu_hours": round(wasted * 0.8, 4),
                },
                rationale=(
                    "Elastic training frameworks let a run shed failed workers and continue "
                    "on the survivors, avoiding the replay cost of a restart."
                ),
                source="detector:restart:elastic",
                claim=self._gpu_claim(run, wasted * 0.8),
                gpu_rate=rate,
            )
        )
        return candidates

    def _sweep_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        sweep_id = str(ev.get("sweep_id", ""))
        wasted = float(ev.get("wasted_gpu_hours", 0.0))
        failed_ids = list(ev.get("failed_run_ids", []))
        runs = [r for r in dataset.training_runs if r.run_id in set(failed_ids)]
        if not runs:
            return []
        rate = self.gpu_rate(runs[0].gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="add_early_stopping",
                description=(
                    f"Add early stopping to sweep {sweep_id} to terminate non-converging "
                    f"runs early, recovering {wasted:.1f} GPU-h from {len(failed_ids)} failed runs."
                ),
                proposed_action={
                    "kind": "add_early_stopping",
                    "sweep_id": sweep_id,
                    "failed_run_count": len(failed_ids),
                    "recovered_gpu_hours": round(wasted * 0.6, 4),
                },
                rationale=(
                    "Early stopping kills runs whose validation metric plateaus or diverges, "
                    "recovering GPU time from runs that would never have converged."
                ),
                source="detector:sweep:early_stopping",
                claim=self._sweep_claim(runs, 0.6),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="reduce_sweep_budget",
                description=(
                    f"Reduce the trial budget for sweep {sweep_id} and switch to Bayesian "
                    f"search to explore fewer, higher-quality configurations."
                ),
                proposed_action={
                    "kind": "reduce_sweep_budget",
                    "sweep_id": sweep_id,
                    "failed_run_count": len(failed_ids),
                    "recovered_gpu_hours": round(wasted * 0.4, 4),
                },
                rationale=(
                    "A Bayesian sweep concentrates trials on promising regions of the search "
                    "space, avoiding the grid/random pattern that wastes budget on bad configs."
                ),
                source="detector:sweep:bayesian",
                claim=self._sweep_claim(runs, 0.4),
                gpu_rate=rate,
            )
        )
        return candidates

    def _checkpoint_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        run = self._find_run(dataset, str(ev.get("run_id", "")))
        if run is None or run.end is None:
            return []
        wasted = float(ev.get("wasted_gpu_hours", 0.0))
        rate = self.gpu_rate(run.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="reduce_checkpoint_frequency",
                description=(
                    f"Reduce checkpoint frequency for run {run.run_id} to cut I/O overhead "
                    f"from {float(ev.get('checkpoint_fraction', 0)):.0%} to under "
                    f"{MIN_CHECKPOINT_FRACTION:.0%}, recovering {wasted:.1f} GPU-h."
                ),
                proposed_action={
                    "kind": "reduce_checkpoint_frequency",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "recovered_gpu_hours": round(wasted, 4),
                },
                rationale=(
                    "Checkpointing more often than necessary turns productive training time "
                    "into synchronous I/O that blocks all GPUs in the run."
                ),
                source="detector:checkpoint:reduce_frequency",
                claim=self._gpu_claim(run, wasted),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="async_checkpointing",
                description=(
                    f"Switch to asynchronous checkpointing for run {run.run_id} so I/O "
                    f"overlaps with the next training step."
                ),
                proposed_action={
                    "kind": "async_checkpointing",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "recovered_gpu_hours": round(wasted * 0.8, 4),
                },
                rationale=(
                    "Async checkpointing pipelines the state write behind the next forward "
                    "pass, recovering most of the synchronous I/O overhead."
                ),
                source="detector:checkpoint:async",
                claim=self._gpu_claim(run, wasted * 0.8),
                gpu_rate=rate,
            )
        )
        return candidates

    # -------------------------------------------------------------- validation

    def validate_candidate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        ev = observation.evidence
        checked = ["run_exists", "wall_hours_positive"]
        violations: list[str] = []

        if observation.signal_type is OpportunityType.NONCONVERGING_SWEEP:
            checked.append("sweep_failure_ratio_above_threshold")
            ratio = float(ev.get("failure_ratio", 0.0))
            if ratio < MIN_SWEEP_FAILURE_RATIO:
                violations.append(
                    f"Sweep failure ratio {ratio:.0%} is below the "
                    f"{MIN_SWEEP_FAILURE_RATIO:.0%} threshold"
                )
            return checked, violations

        run_id = str(ev.get("run_id", ""))
        run = self._find_run(dataset, run_id)
        if run is None:
            violations.append(f"Run {run_id} is not in the dataset")
            return checked, violations
        if run.wall_hours < MIN_WALL_HOURS:
            violations.append(
                f"Run {run_id} wall time {run.wall_hours:.2f}h is below the "
                f"{MIN_WALL_HOURS:.2f}h minimum"
            )

        if observation.signal_type is OpportunityType.DATALOADER_STALL:
            checked.append("stall_fraction_above_threshold")
            fraction = float(ev.get("stall_fraction", 0.0))
            if fraction < MIN_STALL_FRACTION:
                violations.append(
                    f"Stall fraction {fraction:.0%} is below the "
                    f"{MIN_STALL_FRACTION:.0%} threshold"
                )
        elif observation.signal_type is OpportunityType.RESTART_WASTE:
            checked.append("restart_count_positive")
            checked.append("no_checkpoint_resumption")
            if run.restart_count <= 0:
                violations.append("Run has no restarts")
            if run.resumed_from_checkpoint:
                violations.append("Run already resumes from checkpoints")
        elif observation.signal_type is OpportunityType.CHECKPOINT_OVERHEAD:
            checked.append("checkpoint_fraction_above_threshold")
            fraction = float(ev.get("checkpoint_fraction", 0.0))
            if fraction < MIN_CHECKPOINT_FRACTION:
                violations.append(
                    f"Checkpoint fraction {fraction:.0%} is below the "
                    f"{MIN_CHECKPOINT_FRACTION:.0%} threshold"
                )

        return checked, violations

    # ------------------------------------------------------------ presentation

    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        ev = observation.evidence
        wasted = float(ev.get("wasted_gpu_hours", 0.0))
        hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        gpu_hours_month = (wasted / hours) * per_month if hours > 0 else 0.0
        rate = candidate.gpu_rate or self.gpu_rate(str(ev.get("gpu_type", "")))
        dollars = gpu_hours_month * rate
        money = f"{gpu_hours_month:,.0f} GPU-h/month (${dollars:,.0f}/month)"

        if observation.signal_type is OpportunityType.DATALOADER_STALL:
            head = (
                f"Optimize the dataloader for run {observation.resource_id} — increase "
                f"prefetch depth, add workers, or move data to faster storage — worth {money}"
            )
        elif observation.signal_type is OpportunityType.RESTART_WASTE:
            head = (
                f"Enable checkpoint resumption for run {observation.resource_id} so restarts "
                f"replay from the last saved state instead of step zero — worth {money}"
            )
        elif observation.signal_type is OpportunityType.NONCONVERGING_SWEEP:
            head = (
                f"Add early stopping to sweep {observation.resource_id} and consider Bayesian "
                f"search to cut the {int(ev.get('failed_runs', 0))} failed runs — worth {money}"
            )
        else:
            head = (
                f"Reduce checkpoint frequency or switch to async checkpointing for run "
                f"{observation.resource_id} — worth {money}"
            )

        return (
            f"{head}. Confirm with the training team first. Requires human "
            "approval; Natilah changes nothing."
        )

    # --------------------------------------------------------------- claim helpers

    def _gpu_claim(self, run: TrainingRun, wasted_gpu_hours: float) -> ResourceClaim:
        if run.end is None or wasted_gpu_hours <= 0:
            return ResourceClaim(basis="No measurable waste", primary_meter=Meter.GPU_HOURS)
        duration_hours = run.wall_hours
        magnitude = wasted_gpu_hours / duration_hours if duration_hours > 0 else 0.0
        return ResourceClaim(
            resource_intervals=[
                ResourceInterval(
                    meter=Meter.GPU_HOURS,
                    resource_id=run.job_id or run.run_id,
                    start=run.start,
                    end=run.end,
                    magnitude=magnitude,
                )
            ],
            basis=(
                f"{wasted_gpu_hours:.2f} GPU-h wasted over {duration_hours:.1f}h on "
                f"{run.gpu_count} GPU(s)."
            ),
            primary_meter=Meter.GPU_HOURS,
        )

    def _sweep_claim(
        self, failed_runs: list[TrainingRun], recovery_fraction: float
    ) -> ResourceClaim:
        intervals: list[ResourceInterval] = []
        total_wasted = 0.0
        for run in failed_runs:
            if run.end is None or run.wall_hours <= 0:
                continue
            wasted = run.wall_hours * run.gpu_count * recovery_fraction
            magnitude = wasted / run.wall_hours if run.wall_hours > 0 else 0.0
            total_wasted += wasted
            intervals.append(
                ResourceInterval(
                    meter=Meter.GPU_HOURS,
                    resource_id=run.job_id or run.run_id,
                    start=run.start,
                    end=run.end,
                    magnitude=magnitude,
                )
            )
        return ResourceClaim(
            resource_intervals=intervals,
            basis=(
                f"{total_wasted:.2f} GPU-h from {len(failed_runs)} failed sweep runs at "
                f"{recovery_fraction:.0%} recovery."
            ),
            primary_meter=Meter.GPU_HOURS,
        )

    def claim_cap(self, dataset: ClusterDataset, observation: ResourceObservation) -> float:
        ev = observation.evidence
        if observation.signal_type is OpportunityType.NONCONVERGING_SWEEP:
            return float(ev.get("wasted_gpu_hours", 0.0))
        wall_hours = float(ev.get("wall_hours", 0.0))
        gpu_count = int(ev.get("gpu_count", 1))
        return wall_hours * gpu_count

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _find_run(dataset: ClusterDataset, run_id: str) -> TrainingRun | None:
        for run in dataset.training_runs:
            if run.run_id == run_id:
                return run
        return None
