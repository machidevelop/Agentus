"""Storage-efficiency agent.

Objective: the GB-month meter. Orphaned volumes, cold checkpoints, snapshot
sprawl, and duplicate datasets are standing conditions that cost money every
month whether or not a GPU is running.

Four conditions, four shapes of waste:

    orphaned volumes    a PVC that is no longer attached to any pod and has not
                        been read in over 30 days — storage paid for nothing
    cold checkpoints    intermediate checkpoints no run ever reads back, sitting
                        on expensive tiers when they could be archived or purged
    snapshot sprawl     many point-in-time copies against one volume, each
                        costing its full size on the snapshot tier
    duplicate datasets  two materialized artifacts with the same checksum —
                        the same bytes stored and paid for twice
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

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
from natilah.models.resources import Checkpoint, DatasetArtifact, StorageVolume

ORPHAN_DAYS = 30
COLD_CHECKPOINT_DAYS = 14
MAX_SNAPSHOTS_PER_VOLUME = 3
MIN_SIZE_GB = 0.1


def _age_days(ref: datetime, ts: datetime | None) -> float:
    if ts is None:
        return float("inf")
    return max(0.0, (ref - ts).total_seconds() / 86400.0)


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


class StorageEfficiencyAgent(ResourceAgent):
    name = "storage_efficiency_agent"
    objective = AgentObjective.STORAGE_EFFICIENCY
    primary_meter = Meter.GB_MONTHS
    signal_types = (
        OpportunityType.ORPHANED_VOLUME,
        OpportunityType.COLD_CHECKPOINT,
        OpportunityType.SNAPSHOT_SPRAWL,
        OpportunityType.DUPLICATE_DATASET,
    )
    finding_title = "Storage waste"

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        now = datetime.now(timezone.utc)
        return [
            *self._detect_orphaned_volumes(dataset, now),
            *self._detect_cold_checkpoints(dataset, now),
            *self._detect_snapshot_sprawl(dataset, now),
            *self._detect_duplicate_datasets(dataset, now),
        ]

    def _detect_orphaned_volumes(
        self, dataset: ClusterDataset, now: datetime
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for vol in dataset.volumes:
            if vol.attached or vol.size_gb < MIN_SIZE_GB:
                continue
            age = _age_days(now, vol.last_accessed_at or vol.created_at)
            if age < ORPHAN_DAYS:
                continue
            severity = round(min(1.0, (vol.size_gb / 500.0) * (age / 90.0)), 4)
            observations.append(
                ResourceObservation(
                    observation_id=f"orphaned_volume:{vol.volume_id}",
                    signal_type=OpportunityType.ORPHANED_VOLUME,
                    resource_id=vol.volume_id,
                    timestamp=vol.last_accessed_at or vol.created_at,
                    severity=severity,
                    description=(
                        f"Volume {vol.volume_id} ({vol.size_gb:.1f} GB, {vol.tier}) has not been "
                        f"accessed in {age:.0f} days and is not attached to any workload."
                    ),
                    evidence={
                        "volume_id": vol.volume_id,
                        "size_gb": vol.size_gb,
                        "tier": vol.tier,
                        "age_days": round(age, 1),
                        "owner": vol.owner,
                        "created_at": vol.created_at.isoformat(),
                        "last_accessed_at": vol.last_accessed_at.isoformat() if vol.last_accessed_at else None,
                        "signal_reason": f"{vol.size_gb:.1f} GB orphaned for {age:.0f} days on {vol.tier} tier",
                    },
                    data_completeness=0.9 if vol.last_accessed_at else 0.6,
                    signal_strength=round(min(1.0, age / 90.0), 4),
                    recurrence=max(0, sum(1 for v in dataset.volumes if not v.attached and v.owner == vol.owner) - 1),
                )
            )
        return observations

    def _detect_cold_checkpoints(
        self, dataset: ClusterDataset, now: datetime
    ) -> list[ResourceObservation]:
        by_run: dict[str | None, list[Checkpoint]] = defaultdict(list)
        for ckpt in dataset.checkpoints:
            by_run[ckpt.run_id or ckpt.job_id].append(ckpt)

        observations: list[ResourceObservation] = []
        for run_key, checkpoints in by_run.items():
            if len(checkpoints) <= 1:
                continue
            for ckpt in checkpoints:
                if ckpt.is_final or ckpt.size_gb < MIN_SIZE_GB:
                    continue
                age = _age_days(now, ckpt.last_read_at)
                if ckpt.last_read_at is not None and age < COLD_CHECKPOINT_DAYS:
                    continue
                severity = round(min(1.0, (ckpt.size_gb / 100.0) * min(age, 90.0) / 90.0), 4)
                observations.append(
                    ResourceObservation(
                        observation_id=f"cold_checkpoint:{ckpt.checkpoint_id}",
                        signal_type=OpportunityType.COLD_CHECKPOINT,
                        resource_id=ckpt.checkpoint_id,
                        timestamp=ckpt.created_at,
                        severity=severity,
                        description=(
                            f"Checkpoint {ckpt.checkpoint_id} ({ckpt.size_gb:.1f} GB, {ckpt.tier}) "
                            f"from run {run_key or 'unknown'} has not been read in "
                            f"{age:.0f} days and is not marked final."
                        ),
                        affected_job_ids=[ckpt.job_id] if ckpt.job_id else [],
                        evidence={
                            "checkpoint_id": ckpt.checkpoint_id,
                            "run_id": run_key,
                            "size_gb": ckpt.size_gb,
                            "tier": ckpt.tier,
                            "age_days": round(age, 1),
                            "path": ckpt.path,
                            "checkpoints_in_run": len(checkpoints),
                            "signal_reason": f"{ckpt.size_gb:.1f} GB checkpoint unread for {age:.0f} days",
                        },
                        data_completeness=0.85 if ckpt.last_read_at else 0.5,
                        signal_strength=round(min(1.0, age / 30.0), 4),
                        recurrence=max(0, sum(1 for c in checkpoints if not c.is_final and c.checkpoint_id != ckpt.checkpoint_id) - 1),
                    )
                )
        return observations

    def _detect_snapshot_sprawl(
        self, dataset: ClusterDataset, now: datetime
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        volumes_with_snaps: dict[str, list] = defaultdict(list)
        for snap in dataset.snapshots:
            volumes_with_snaps[snap.volume_id].append(snap)

        for volume_id, snaps in volumes_with_snaps.items():
            if len(snaps) <= MAX_SNAPSHOTS_PER_VOLUME:
                continue
            excess = len(snaps) - MAX_SNAPSHOTS_PER_VOLUME
            total_gb = sum(s.size_gb for s in snaps)
            excess_gb = sum(s.size_gb for s in sorted(snaps, key=lambda s: s.created_at)[:-MAX_SNAPSHOTS_PER_VOLUME])
            severity = round(min(1.0, excess / 10.0), 4)
            oldest = min(s.created_at for s in snaps)
            observations.append(
                ResourceObservation(
                    observation_id=f"snapshot_sprawl:{volume_id}",
                    signal_type=OpportunityType.SNAPSHOT_SPRAWL,
                    resource_id=volume_id,
                    timestamp=oldest,
                    severity=severity,
                    description=(
                        f"Volume {volume_id} has {len(snaps)} snapshots ({total_gb:.1f} GB total); "
                        f"{excess} older snapshots ({excess_gb:.1f} GB) exceed the retention threshold."
                    ),
                    evidence={
                        "volume_id": volume_id,
                        "snapshot_count": len(snaps),
                        "excess_count": excess,
                        "total_gb": round(total_gb, 2),
                        "excess_gb": round(excess_gb, 2),
                        "oldest_snapshot": oldest.isoformat(),
                        "tier": snaps[0].tier if snaps else "object",
                        "signal_reason": f"{excess} excess snapshots totalling {excess_gb:.1f} GB",
                    },
                    data_completeness=0.95,
                    signal_strength=round(min(1.0, excess_gb / 200.0), 4),
                    recurrence=max(0, sum(1 for v, s in volumes_with_snaps.items() if len(s) > MAX_SNAPSHOTS_PER_VOLUME) - 1),
                )
            )
        return observations

    def _detect_duplicate_datasets(
        self, dataset: ClusterDataset, now: datetime
    ) -> list[ResourceObservation]:
        by_checksum: dict[str, list[DatasetArtifact]] = defaultdict(list)
        for artifact in dataset.artifacts:
            if artifact.checksum and artifact.size_gb >= MIN_SIZE_GB:
                by_checksum[artifact.checksum].append(artifact)

        observations: list[ResourceObservation] = []
        for checksum, dupes in by_checksum.items():
            if len(dupes) <= 1:
                continue
            dupes_sorted = sorted(dupes, key=lambda a: a.created_at)
            keeper = dupes_sorted[0]
            redundant = dupes_sorted[1:]
            redundant_gb = sum(a.size_gb for a in redundant)
            severity = round(min(1.0, redundant_gb / 500.0), 4)
            observations.append(
                ResourceObservation(
                    observation_id=f"duplicate_dataset:{checksum[:16]}",
                    signal_type=OpportunityType.DUPLICATE_DATASET,
                    resource_id=checksum,
                    timestamp=keeper.created_at,
                    severity=severity,
                    description=(
                        f"{len(dupes)} copies of dataset (checksum {checksum[:16]}...) total "
                        f"{redundant_gb:.1f} GB of redundant storage across "
                        f"{len(redundant)} extra copies."
                    ),
                    evidence={
                        "checksum": checksum,
                        "copy_count": len(dupes),
                        "redundant_count": len(redundant),
                        "redundant_gb": round(redundant_gb, 2),
                        "keeper_id": keeper.artifact_id,
                        "redundant_ids": [a.artifact_id for a in redundant],
                        "tier": keeper.tier,
                        "signal_reason": f"{len(redundant)} redundant copies totalling {redundant_gb:.1f} GB",
                    },
                    data_completeness=1.0 if all(a.checksum for a in dupes) else 0.7,
                    signal_strength=round(min(1.0, redundant_gb / 200.0), 4),
                    recurrence=max(0, len(redundant) - 1),
                )
            )
        return observations

    # -------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.ORPHANED_VOLUME:
            return self._orphan_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.COLD_CHECKPOINT:
            return self._checkpoint_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.SNAPSHOT_SPRAWL:
            return self._snapshot_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.DUPLICATE_DATASET:
            return self._duplicate_candidates(dataset, observation)
        return []

    def _orphan_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        size_gb = float(ev.get("size_gb") or 0.0)
        tier = str(ev.get("tier") or "ssd")
        volume_id = observation.resource_id
        window = self._storage_window(dataset, observation)
        if window is None or size_gb <= 0:
            return []
        start, end = window
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="delete_orphan",
                description=f"Delete orphaned volume {volume_id} ({size_gb:.1f} GB, {tier}).",
                proposed_action={
                    "kind": "delete_volume",
                    "volume_id": volume_id,
                    "size_gb": size_gb,
                    "recovered_gb": size_gb,
                },
                rationale=(
                    "Volume is not attached and has not been accessed in over "
                    f"{float(ev.get('age_days') or 0):.0f} days; deleting it recovers 100% of "
                    "the storage cost."
                ),
                source="detector:orphan:delete",
                claim=self._gb_claim(
                    volume_id, start, end, size_gb,
                    f"Full {size_gb:.1f} GB of orphaned volume on {tier} tier.",
                ),
                tier=tier,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="archive_orphan",
                description=(
                    f"Move orphaned volume {volume_id} to archive tier instead of deleting."
                ),
                proposed_action={
                    "kind": "archive_volume",
                    "volume_id": volume_id,
                    "size_gb": size_gb,
                    "from_tier": tier,
                    "to_tier": "archive",
                },
                rationale=(
                    "If the data might be needed again, archiving captures the tier price "
                    "difference without destroying the data."
                ),
                source="detector:orphan:archive",
                claim=self._gb_claim(
                    volume_id, start, end, size_gb,
                    f"Tier delta: {tier} to archive for {size_gb:.1f} GB.",
                ),
                tier=tier,
            )
        )

        return candidates

    def _checkpoint_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        size_gb = float(ev.get("size_gb") or 0.0)
        tier = str(ev.get("tier") or "object")
        ckpt_id = observation.resource_id
        window = self._storage_window(dataset, observation)
        if window is None or size_gb <= 0:
            return []
        start, end = window
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="delete_cold_checkpoint",
                description=f"Delete cold checkpoint {ckpt_id} ({size_gb:.1f} GB, {tier}).",
                proposed_action={
                    "kind": "delete_checkpoint",
                    "checkpoint_id": ckpt_id,
                    "size_gb": size_gb,
                    "recovered_gb": size_gb,
                },
                rationale=(
                    "Intermediate checkpoint has not been read back and a more recent "
                    "or final checkpoint exists for the same run."
                ),
                source="detector:checkpoint:delete",
                claim=self._gb_claim(
                    ckpt_id, start, end, size_gb,
                    f"Full {size_gb:.1f} GB of cold checkpoint on {tier} tier.",
                ),
                tier=tier,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="archive_cold_checkpoint",
                description=f"Move checkpoint {ckpt_id} to archive tier.",
                proposed_action={
                    "kind": "archive_checkpoint",
                    "checkpoint_id": ckpt_id,
                    "size_gb": size_gb,
                    "from_tier": tier,
                    "to_tier": "archive",
                },
                rationale=(
                    "Keeps the checkpoint recoverable in case of a training regression, "
                    "but at archive-tier pricing instead of the current tier."
                ),
                source="detector:checkpoint:archive",
                claim=self._gb_claim(
                    ckpt_id, start, end, size_gb,
                    f"Tier delta: {tier} to archive for {size_gb:.1f} GB checkpoint.",
                ),
                tier=tier,
            )
        )

        return candidates

    def _snapshot_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        excess_gb = float(ev.get("excess_gb") or 0.0)
        excess_count = int(ev.get("excess_count") or 0)
        total_count = int(ev.get("snapshot_count") or 0)
        tier = str(ev.get("tier") or "object")
        volume_id = observation.resource_id
        window = self._storage_window(dataset, observation)
        if window is None or excess_gb <= 0:
            return []
        start, end = window
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="prune_old_snapshots",
                description=(
                    f"Delete the {excess_count} oldest snapshots of volume {volume_id}, "
                    f"keeping the newest {MAX_SNAPSHOTS_PER_VOLUME}."
                ),
                proposed_action={
                    "kind": "prune_snapshots",
                    "volume_id": volume_id,
                    "keep_count": MAX_SNAPSHOTS_PER_VOLUME,
                    "delete_count": excess_count,
                    "recovered_gb": excess_gb,
                },
                rationale=(
                    f"Volume has {total_count} snapshots; the oldest {excess_count} are "
                    f"superseded by more recent ones and occupy {excess_gb:.1f} GB."
                ),
                source="detector:snapshot:prune_all_excess",
                claim=self._gb_claim(
                    volume_id, start, end, excess_gb,
                    f"{excess_count} excess snapshots totalling {excess_gb:.1f} GB on {tier} tier.",
                ),
                tier=tier,
            )
        )

        half_excess = excess_count // 2
        if half_excess >= 1:
            snaps = dataset.snapshots_for_volume(volume_id)
            half_snaps = sorted(snaps, key=lambda s: s.created_at)[:half_excess]
            half_gb = sum(s.size_gb for s in half_snaps)
            candidates.append(
                ResourceCandidate(
                    kind="prune_half_snapshots",
                    description=(
                        f"Delete the {half_excess} oldest snapshots of volume {volume_id}, "
                        f"a conservative first pass."
                    ),
                    proposed_action={
                        "kind": "prune_snapshots",
                        "volume_id": volume_id,
                        "keep_count": total_count - half_excess,
                        "delete_count": half_excess,
                        "recovered_gb": half_gb,
                    },
                    rationale="A smaller prune for teams not yet confident in their retention policy.",
                    source="detector:snapshot:prune_half",
                    claim=self._gb_claim(
                        volume_id, start, end, half_gb,
                        f"Half of excess snapshots: {half_excess} totalling {half_gb:.1f} GB.",
                    ),
                    tier=tier,
                )
            )

        return candidates

    def _duplicate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        redundant_gb = float(ev.get("redundant_gb") or 0.0)
        redundant_ids = list(ev.get("redundant_ids") or [])
        keeper_id = str(ev.get("keeper_id") or "")
        tier = str(ev.get("tier") or "object")
        checksum = observation.resource_id
        window = self._storage_window(dataset, observation)
        if window is None or redundant_gb <= 0 or not redundant_ids:
            return []
        start, end = window
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="deduplicate_datasets",
                description=(
                    f"Delete {len(redundant_ids)} redundant copies of dataset "
                    f"{checksum[:16]}..., keeping {keeper_id}."
                ),
                proposed_action={
                    "kind": "deduplicate_dataset",
                    "checksum": checksum,
                    "keep_artifact_id": keeper_id,
                    "delete_artifact_ids": redundant_ids,
                    "recovered_gb": redundant_gb,
                },
                rationale=(
                    "Identical checksums confirm these are byte-for-byte the same data; "
                    "all consumers can be redirected to the single keeper."
                ),
                source="detector:duplicate:delete_all",
                claim=self._gb_claim(
                    checksum, start, end, redundant_gb,
                    f"{len(redundant_ids)} redundant copies totalling {redundant_gb:.1f} GB.",
                ),
                tier=tier,
            )
        )

        if len(redundant_ids) > 1:
            first_redundant = redundant_ids[:1]
            first_gb = 0.0
            by_id = {a.artifact_id: a for a in dataset.artifacts}
            for aid in first_redundant:
                art = by_id.get(aid)
                if art:
                    first_gb += art.size_gb
            if first_gb > 0:
                candidates.append(
                    ResourceCandidate(
                        kind="deduplicate_one",
                        description=(
                            f"Delete one redundant copy ({first_redundant[0]}) of dataset "
                            f"{checksum[:16]}... as a first step."
                        ),
                        proposed_action={
                            "kind": "deduplicate_dataset",
                            "checksum": checksum,
                            "keep_artifact_id": keeper_id,
                            "delete_artifact_ids": first_redundant,
                            "recovered_gb": first_gb,
                        },
                        rationale="A single-copy removal to validate the dedup process before bulk.",
                        source="detector:duplicate:delete_one",
                        claim=self._gb_claim(
                            checksum, start, end, first_gb,
                            f"One redundant copy: {first_gb:.1f} GB.",
                        ),
                        tier=tier,
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
        action = candidate.proposed_action or {}
        ev = observation.evidence
        checked = ["resource_exists_in_dataset", "size_positive"]
        violations: list[str] = []

        size = float(action.get("size_gb") or action.get("recovered_gb") or 0.0)
        if size <= 0:
            violations.append("Candidate recovers no storage")

        if observation.signal_type is OpportunityType.ORPHANED_VOLUME:
            checked += ["volume_not_attached", "volume_not_recently_accessed"]
            vol_id = str(action.get("volume_id") or "")
            vol = next((v for v in dataset.volumes if v.volume_id == vol_id), None)
            if vol is None:
                violations.append(f"Volume {vol_id} is not in the storage inventory")
            elif vol.attached:
                violations.append(f"Volume {vol_id} is currently attached to {vol.attached_to_job_id}")

        elif observation.signal_type is OpportunityType.COLD_CHECKPOINT:
            checked += ["checkpoint_not_final", "checkpoint_has_sibling"]
            ckpt_id = str(action.get("checkpoint_id") or "")
            ckpt = next((c for c in dataset.checkpoints if c.checkpoint_id == ckpt_id), None)
            if ckpt is None:
                violations.append(f"Checkpoint {ckpt_id} is not in the inventory")
            elif ckpt.is_final:
                violations.append(f"Checkpoint {ckpt_id} is marked as final and must not be deleted")
            else:
                siblings = [
                    c for c in dataset.checkpoints
                    if (c.run_id or c.job_id) == (ckpt.run_id or ckpt.job_id)
                    and c.checkpoint_id != ckpt_id
                ]
                if not siblings:
                    violations.append(
                        f"Checkpoint {ckpt_id} is the only checkpoint for its run"
                    )

        elif observation.signal_type is OpportunityType.SNAPSHOT_SPRAWL:
            checked += ["volume_has_excess_snapshots"]
            vol_id = str(action.get("volume_id") or "")
            snaps = dataset.snapshots_for_volume(vol_id)
            keep = int(action.get("keep_count") or MAX_SNAPSHOTS_PER_VOLUME)
            if len(snaps) <= keep:
                violations.append(
                    f"Volume {vol_id} has only {len(snaps)} snapshots, at or below the "
                    f"retention threshold of {keep}"
                )

        elif observation.signal_type is OpportunityType.DUPLICATE_DATASET:
            checked += ["checksum_match_confirmed", "keeper_exists"]
            keeper_id = str(action.get("keep_artifact_id") or "")
            if not any(a.artifact_id == keeper_id for a in dataset.artifacts):
                violations.append(f"Keeper artifact {keeper_id} is not in the inventory")
            delete_ids = list(action.get("delete_artifact_ids") or [])
            missing = [d for d in delete_ids if not any(a.artifact_id == d for a in dataset.artifacts)]
            if missing:
                violations.append(f"Redundant artifact(s) not found: {missing[:3]}")

        return checked, violations

    # ------------------------------------------------------------ presentation

    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        gb = float((candidate.proposed_action or {}).get("recovered_gb") or 0.0)
        hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        gb_months = (gb * hours / (30.0 * 24.0)) if hours > 0 else 0.0
        monthly_gb = (gb_months / hours) * per_month if hours > 0 else 0.0
        tier = candidate.tier or "ssd"
        rate = self.pricing.rate_for(Meter.GB_MONTHS, tier=tier)
        dollars = monthly_gb * rate
        money = f"{monthly_gb:,.0f} GB-months/month (${dollars:,.0f}/month)"
        ev = observation.evidence
        action = candidate.proposed_action or {}

        if observation.signal_type is OpportunityType.ORPHANED_VOLUME:
            kind = action.get("kind", "")
            if kind == "archive_volume":
                head = (
                    f"Archive orphaned volume {observation.resource_id} "
                    f"({gb:.0f} GB, {tier}) to archive tier — worth {money}"
                )
            else:
                head = (
                    f"Delete orphaned volume {observation.resource_id} "
                    f"({gb:.0f} GB, {tier}, unaccessed for {float(ev.get('age_days') or 0):.0f} "
                    f"days) — worth {money}"
                )

        elif observation.signal_type is OpportunityType.COLD_CHECKPOINT:
            kind = action.get("kind", "")
            if kind == "archive_checkpoint":
                head = (
                    f"Archive cold checkpoint {observation.resource_id} ({gb:.0f} GB) "
                    f"to archive tier — worth {money}"
                )
            else:
                head = (
                    f"Delete cold checkpoint {observation.resource_id} ({gb:.0f} GB, "
                    f"unread for {float(ev.get('age_days') or 0):.0f} days) — worth {money}"
                )

        elif observation.signal_type is OpportunityType.SNAPSHOT_SPRAWL:
            head = (
                f"Prune {int(action.get('delete_count') or 0)} old snapshots from volume "
                f"{observation.resource_id} ({gb:.0f} GB recoverable) — worth {money}"
            )

        else:
            head = (
                f"Deduplicate {len(action.get('delete_artifact_ids') or [])} redundant "
                f"copies of dataset {str(observation.resource_id)[:16]}... ({gb:.0f} GB) "
                f"— worth {money}"
            )

        return (
            f"{head}. Confirm with the storage and data owners first. Requires human "
            "approval; Natilah changes nothing."
        )

    # ---------------------------------------------------------------- claim helpers

    def claim_cap(self, dataset: ClusterDataset, observation: ResourceObservation) -> float:
        ev = observation.evidence
        if observation.signal_type is OpportunityType.SNAPSHOT_SPRAWL:
            return float(ev.get("total_gb") or float("inf"))
        if observation.signal_type is OpportunityType.DUPLICATE_DATASET:
            return float(ev.get("redundant_gb") or float("inf"))
        return float(ev.get("size_gb") or float("inf"))

    def _gb_claim(
        self,
        resource_id: str,
        start: datetime,
        end: datetime,
        size_gb: float,
        basis: str,
    ) -> ResourceClaim:
        hours = _hours(start, end)
        if hours <= 0 or size_gb <= 0:
            return ResourceClaim(
                resource_intervals=[], basis=basis, primary_meter=Meter.GB_MONTHS
            )
        return ResourceClaim(
            resource_intervals=[
                ResourceInterval(
                    meter=Meter.GB_MONTHS,
                    resource_id=resource_id,
                    start=start,
                    end=end,
                    magnitude=size_gb,
                ),
            ],
            basis=basis,
            primary_meter=Meter.GB_MONTHS,
        )

    def _storage_window(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> tuple[datetime, datetime] | None:
        window = dataset.window()
        if window is not None:
            return window
        now = datetime.now(timezone.utc)
        return now - timedelta(days=30), now
