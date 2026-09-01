"""Read-only storage inventory connector.

The GB-month meter needs four things no scheduler records: which volumes
exist, which snapshots hang off them, which checkpoints a run wrote, and which
dataset artifacts were materialized more than once. Storage inventories come
from a dozen different places — CSI/PVC listings, `aws s3 ls`, a Lustre or
Weka report, a checkpoint index — so this connector normalizes dumps rather
than speaking one vendor's API.

Every path here is a read: a JSON file, a directory of JSON files, or a dict
already in memory. No client that can write or delete is imported, and no
record produced by this module implies an action.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from natilah.models.domain import ClusterDataset, ValidationIssue
from natilah.models.resources import (
    Checkpoint,
    DatasetArtifact,
    StorageSnapshot,
    StorageVolume,
)
from natilah.safety.guards import Action, SafetyGuard

logger = logging.getLogger(__name__)

# Tiers differ by an order of magnitude in price, so a vendor storage class is
# mapped onto the tier keys `MeterPricing` knows rather than passed through.
TIER_ALIASES: dict[str, str] = {
    "gp2": "ssd",
    "gp3": "ssd",
    "ssd": "ssd",
    "pd-ssd": "ssd",
    "premium-ssd": "ssd",
    "premium_lrs": "ssd",
    "managed-premium": "ssd",
    "io1": "nvme",
    "io2": "nvme",
    "nvme": "nvme",
    "local-ssd": "nvme",
    "local-nvme": "nvme",
    "scratch": "nvme",
    "block": "block",
    "ebs": "block",
    "standard": "standard",
    "pd-standard": "standard",
    "hdd": "standard",
    "st1": "standard",
    "sc1": "standard",
    "s3": "object",
    "gcs": "object",
    "gs": "object",
    "blob": "object",
    "object": "object",
    "standard-ia": "object",
    "nearline": "object",
    "coldline": "archive",
    "glacier": "archive",
    "deep-archive": "archive",
    "archive": "archive",
    "tape": "archive",
}

_SIZE_SUFFIXES: dict[str, float] = {
    "ki": 1.0 / 1_048_576,
    "mi": 1.0 / 1024,
    "gi": 1.0,
    "ti": 1024.0,
    "pi": 1_048_576.0,
    "k": 1e-6,
    "m": 1e-3,
    "g": 1.0,
    "t": 1000.0,
    "p": 1e6,
    "b": 1e-9,
}


@dataclass(frozen=True)
class StorageConnectorConfig:
    """What the dump cannot tell us, stated once instead of guessed per record."""

    source: str = "storage_inventory"
    default_volume_tier: str = "ssd"
    default_snapshot_tier: str = "object"
    default_checkpoint_tier: str = "object"
    default_artifact_tier: str = "object"
    # A checkpoint whose path says it is the artifact of record is never a
    # reclaim candidate, so the marker has to survive ingestion.
    final_checkpoint_markers: tuple[str, ...] = ("final", "best", "release", "production")
    min_size_gb: float = 0.0


@dataclass
class StorageRecords:
    """The four normalized record types one inventory produced."""

    volumes: list[StorageVolume] = field(default_factory=list)
    snapshots: list[StorageSnapshot] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    artifacts: list[DatasetArtifact] = field(default_factory=list)

    @property
    def total_gb(self) -> float:
        return sum(
            r.size_gb
            for r in [*self.volumes, *self.snapshots, *self.checkpoints, *self.artifacts]
        )

    def counts(self) -> dict[str, int]:
        return {
            "volumes": len(self.volumes),
            "snapshots": len(self.snapshots),
            "checkpoints": len(self.checkpoints),
            "artifacts": len(self.artifacts),
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def parse_timestamp(value: Any) -> datetime | None:
    """Accepts ISO strings, epoch seconds, and datetimes; always returns UTC.

    Naive timestamps are read as UTC rather than dropped: an inventory that
    omits the offset is still evidence, and mixing naive and aware datetimes
    downstream is what actually breaks the claim arithmetic.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.debug("Unparseable storage timestamp %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_size_gb(value: Any) -> float:
    """Sizes arrive as `500`, `"500Gi"`, `"1Ti"`, or bytes. All become GB."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(" ", "")
    for suffix, factor in sorted(_SIZE_SUFFIXES.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(suffix):
            try:
                return float(text[: -len(suffix)]) * factor
            except ValueError:
                return 0.0
    try:
        return float(text)
    except ValueError:
        logger.debug("Unparseable storage size %r", value)
        return 0.0


def normalize_tier(value: Any, default: str) -> str:
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in TIER_ALIASES:
        return TIER_ALIASES[text]
    for alias, tier in TIER_ALIASES.items():
        if alias in text:
            return tier
    return default


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "attached", "bound", "mounted"}


# ---------------------------------------------------------------------------
# StorageConnector
# ---------------------------------------------------------------------------


class StorageConnector:
    """Read-only storage connector. Lists inventory; never mutates it."""

    def __init__(
        self,
        *,
        volumes: list[dict[str, Any]] | None = None,
        snapshots: list[dict[str, Any]] | None = None,
        checkpoints: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        config: StorageConnectorConfig | None = None,
    ):
        self.config = config or StorageConnectorConfig()
        self.volumes_raw = list(volumes or [])
        self.snapshots_raw = list(snapshots or [])
        self.checkpoints_raw = list(checkpoints or [])
        self.artifacts_raw = list(artifacts or [])
        self.safety = SafetyGuard()

    # ---------------------------------------------------------------- loaders

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], config: StorageConnectorConfig | None = None
    ) -> "StorageConnector":
        """Load an in-memory inventory. `items` wrappers are unwrapped."""
        return cls(
            volumes=_items(payload.get("volumes")),
            snapshots=_items(payload.get("snapshots")),
            checkpoints=_items(payload.get("checkpoints")),
            artifacts=_items(payload.get("artifacts") or payload.get("datasets")),
            config=config,
        )

    @classmethod
    def from_json(
        cls, source: str | Path | dict[str, Any], config: StorageConnectorConfig | None = None
    ) -> "StorageConnector":
        """Load from a JSON file, a JSON string, or a dict already parsed."""
        if isinstance(source, dict):
            return cls.from_dict(source, config=config)
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.exists() else str(source)
        return cls.from_dict(json.loads(text), config=config)

    @classmethod
    def from_snapshot_dir(
        cls, directory: str | Path, config: StorageConnectorConfig | None = None
    ) -> "StorageConnector":
        """Load a directory of `volumes.json`, `snapshots.json`, ... dumps."""
        root = Path(directory)
        payload: dict[str, Any] = {}
        for key in ("volumes", "snapshots", "checkpoints", "artifacts"):
            candidate = root / f"{key}.json"
            if candidate.exists():
                payload[key] = json.loads(candidate.read_text(encoding="utf-8"))
        return cls.from_dict(payload, config=config)

    # ----------------------------------------------------------------- public

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not any(
            [self.volumes_raw, self.snapshots_raw, self.checkpoints_raw, self.artifacts_raw]
        ):
            issues.append(
                ValidationIssue(field="storage", message="No storage inventory provided")
            )
        records = self.build_records()
        for name, raw, parsed in (
            ("volumes", self.volumes_raw, records.volumes),
            ("snapshots", self.snapshots_raw, records.snapshots),
            ("checkpoints", self.checkpoints_raw, records.checkpoints),
            ("artifacts", self.artifacts_raw, records.artifacts),
        ):
            dropped = len(raw) - len(parsed)
            if dropped > 0:
                issues.append(
                    ValidationIssue(
                        field=name,
                        message=f"{dropped} record(s) dropped: missing id, size, or created_at",
                    )
                )
        if records.volumes and not any(v.last_accessed_at for v in records.volumes):
            issues.append(
                ValidationIssue(
                    field="volumes",
                    message="No volume carries last_accessed_at; orphan findings will be weak",
                )
            )
        known = {s.volume_id for s in records.snapshots} - {v.volume_id for v in records.volumes}
        if known:
            issues.append(
                ValidationIssue(
                    field="snapshots",
                    message=f"{len(known)} snapshot volume(s) absent from the volume inventory",
                )
            )
        return issues

    def build_records(self) -> StorageRecords:
        self.safety.check_action(Action(name="read_storage_inventory", is_read_only=True))
        records = StorageRecords()
        for raw in self.volumes_raw:
            volume = self._volume(raw)
            if volume is not None:
                records.volumes.append(volume)
        for raw in self.snapshots_raw:
            snapshot = self._snapshot(raw)
            if snapshot is not None:
                records.snapshots.append(snapshot)
        for raw in self.checkpoints_raw:
            checkpoint = self._checkpoint(raw)
            if checkpoint is not None:
                records.checkpoints.append(checkpoint)
        for raw in self.artifacts_raw:
            artifact = self._artifact(raw)
            if artifact is not None:
                records.artifacts.append(artifact)
        return records

    def attach(self, dataset: ClusterDataset) -> ClusterDataset:
        """Fill the storage side of an existing dataset, in place."""
        records = self.build_records()
        dataset.volumes = records.volumes
        dataset.snapshots = records.snapshots
        dataset.checkpoints = records.checkpoints
        dataset.artifacts = records.artifacts
        dataset.invalidate_indexes()
        return dataset

    def build_dataset(self) -> ClusterDataset:
        """A storage-only dataset, for clusters whose compute is ingested apart."""
        return self.attach(ClusterDataset())

    # ------------------------------------------------------------- normalizing

    def _volume(self, raw: dict[str, Any]) -> StorageVolume | None:
        volume_id = _pick(raw, "volume_id", "volumeId", "id", "pvc", "claim_name")
        created = parse_timestamp(_pick(raw, "created_at", "creationTimestamp", "created"))
        if volume_id is None or created is None:
            return None
        size_gb = parse_size_gb(_pick(raw, "size_gb", "sizeGb", "capacity", "size", "capacity_gb"))
        if size_gb < self.config.min_size_gb:
            return None
        job_id = _pick(raw, "attached_to_job_id", "job_id", "pod", "consumer")
        attached = _as_bool(_pick(raw, "attached", "in_use", "mounted", "bound"))
        return StorageVolume(
            volume_id=str(volume_id),
            name=str(_pick(raw, "name", "volume_name", "volumeName") or volume_id),
            size_gb=size_gb,
            tier=normalize_tier(
                _pick(raw, "tier", "storage_class", "storageClassName", "class", "type"),
                self.config.default_volume_tier,
            ),
            created_at=created,
            last_accessed_at=parse_timestamp(
                _pick(raw, "last_accessed_at", "lastAccessed", "atime", "last_read_at")
            ),
            attached_to_job_id=str(job_id) if job_id is not None else None,
            # An inventory that omits the flag but names a consumer is treated
            # as attached: under-claiming an orphan is the cheap mistake.
            attached=attached if attached is not None else job_id is not None,
            node_id=_str_or_none(_pick(raw, "node_id", "node", "nodeName")),
            owner=str(_pick(raw, "owner", "user", "team", "namespace") or ""),
            labels={str(k): str(v) for k, v in (raw.get("labels") or {}).items()},
        )

    def _snapshot(self, raw: dict[str, Any]) -> StorageSnapshot | None:
        snapshot_id = _pick(raw, "snapshot_id", "snapshotId", "id", "name")
        volume_id = _pick(raw, "volume_id", "volumeId", "source_volume", "sourceVolumeId")
        created = parse_timestamp(_pick(raw, "created_at", "creationTimestamp", "created"))
        if snapshot_id is None or volume_id is None or created is None:
            return None
        return StorageSnapshot(
            snapshot_id=str(snapshot_id),
            volume_id=str(volume_id),
            size_gb=parse_size_gb(_pick(raw, "size_gb", "sizeGb", "size", "capacity")),
            created_at=created,
            tier=normalize_tier(
                _pick(raw, "tier", "storage_class", "class"), self.config.default_snapshot_tier
            ),
            owner=str(_pick(raw, "owner", "user", "team") or ""),
        )

    def _checkpoint(self, raw: dict[str, Any]) -> Checkpoint | None:
        checkpoint_id = _pick(raw, "checkpoint_id", "id", "name", "path")
        created = parse_timestamp(_pick(raw, "created_at", "created", "mtime", "written_at"))
        if checkpoint_id is None or created is None:
            return None
        path = str(_pick(raw, "path", "uri", "location") or "")
        explicit_final = _as_bool(_pick(raw, "is_final", "final"))
        return Checkpoint(
            checkpoint_id=str(checkpoint_id),
            job_id=_str_or_none(_pick(raw, "job_id", "jobId")),
            run_id=_str_or_none(_pick(raw, "run_id", "runId", "experiment_id")),
            path=path,
            size_gb=parse_size_gb(_pick(raw, "size_gb", "sizeGb", "size", "bytes_gb")),
            created_at=created,
            last_read_at=parse_timestamp(
                _pick(raw, "last_read_at", "lastRead", "atime", "last_accessed_at")
            ),
            tier=normalize_tier(
                _pick(raw, "tier", "storage_class", "class"), self.config.default_checkpoint_tier
            ),
            is_final=explicit_final if explicit_final is not None else self._looks_final(path),
        )

    def _artifact(self, raw: dict[str, Any]) -> DatasetArtifact | None:
        artifact_id = _pick(raw, "artifact_id", "id", "name", "path")
        created = parse_timestamp(_pick(raw, "created_at", "created", "mtime"))
        if artifact_id is None or created is None:
            return None
        return DatasetArtifact(
            artifact_id=str(artifact_id),
            path=str(_pick(raw, "path", "uri", "location") or ""),
            size_gb=parse_size_gb(_pick(raw, "size_gb", "sizeGb", "size")),
            checksum=str(_pick(raw, "checksum", "sha256", "md5", "etag", "digest") or ""),
            created_at=created,
            last_read_at=parse_timestamp(
                _pick(raw, "last_read_at", "lastRead", "atime", "last_accessed_at")
            ),
            tier=normalize_tier(
                _pick(raw, "tier", "storage_class", "class"), self.config.default_artifact_tier
            ),
            owner=str(_pick(raw, "owner", "user", "team") or ""),
        )

    def _looks_final(self, path: str) -> bool:
        lowered = path.lower()
        return any(marker in lowered for marker in self.config.final_checkpoint_markers)


def _items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    return [row for row in payload if isinstance(row, dict)]


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)
