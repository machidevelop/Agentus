"""Read-only inference serving connector.

The replica-hours meter needs two things no scheduler records: which serving
endpoints exist and how hard they are actually working.  Endpoint inventories
come from Kubernetes Deployment/StatefulSet listings, Triton or vLLM management
APIs, or internal service registries; metric samples come from Prometheus
scrapers, custom exporters, or cloud monitoring dumps.  This connector
normalizes any of those into ``InferenceEndpoint`` and ``InferenceMetricSample``
and does nothing else.

Every path here is a read: a JSON file, a directory of JSON files, or a dict
already in memory.  No client that can mutate a deployment is imported, and no
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
from natilah.models.resources import InferenceEndpoint, InferenceMetricSample
from natilah.safety.guards import Action, SafetyGuard

logger = logging.getLogger(__name__)


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _parse_timestamp(value: Any) -> datetime | None:
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
        logger.debug("Unparseable inference timestamp %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "enabled"}


def _int_or(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value if v is not None]


def _items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    return [row for row in payload if isinstance(row, dict)]


@dataclass(frozen=True)
class InferenceConnectorConfig:
    source: str = "inference_inventory"
    default_gpus_per_replica: int = 1
    default_max_batch_size: int = 1
    min_replicas_for_ingestion: int = 0


@dataclass
class InferenceRecords:
    endpoints: list[InferenceEndpoint] = field(default_factory=list)
    samples: list[InferenceMetricSample] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "endpoints": len(self.endpoints),
            "samples": len(self.samples),
        }


class InferenceConnector:
    """Read-only inference connector. Lists endpoints and metrics; never mutates."""

    def __init__(
        self,
        *,
        endpoints: list[dict[str, Any]] | None = None,
        samples: list[dict[str, Any]] | None = None,
        config: InferenceConnectorConfig | None = None,
    ):
        self.config = config or InferenceConnectorConfig()
        self.endpoints_raw = list(endpoints or [])
        self.samples_raw = list(samples or [])
        self.safety = SafetyGuard()

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], config: InferenceConnectorConfig | None = None
    ) -> "InferenceConnector":
        return cls(
            endpoints=_items(payload.get("endpoints") or payload.get("deployments")),
            samples=_items(payload.get("samples") or payload.get("metrics")),
            config=config,
        )

    @classmethod
    def from_json(
        cls, source: str | Path | dict[str, Any], config: InferenceConnectorConfig | None = None
    ) -> "InferenceConnector":
        if isinstance(source, dict):
            return cls.from_dict(source, config=config)
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.exists() else str(source)
        return cls.from_dict(json.loads(text), config=config)

    @classmethod
    def from_snapshot_dir(
        cls, directory: str | Path, config: InferenceConnectorConfig | None = None
    ) -> "InferenceConnector":
        root = Path(directory)
        payload: dict[str, Any] = {}
        for key in ("endpoints", "deployments", "samples", "metrics"):
            candidate = root / f"{key}.json"
            if candidate.exists():
                payload[key] = json.loads(candidate.read_text(encoding="utf-8"))
        return cls.from_dict(payload, config=config)

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.endpoints_raw and not self.samples_raw:
            issues.append(
                ValidationIssue(field="inference", message="No inference inventory provided")
            )
        records = self.build_records()
        ep_dropped = len(self.endpoints_raw) - len(records.endpoints)
        if ep_dropped > 0:
            issues.append(
                ValidationIssue(
                    field="endpoints",
                    message=f"{ep_dropped} endpoint(s) dropped: missing id or created_at",
                )
            )
        sample_dropped = len(self.samples_raw) - len(records.samples)
        if sample_dropped > 0:
            issues.append(
                ValidationIssue(
                    field="samples",
                    message=f"{sample_dropped} sample(s) dropped: missing endpoint_id or timestamp",
                )
            )
        ep_ids = {ep.endpoint_id for ep in records.endpoints}
        orphan_ids = {s.endpoint_id for s in records.samples} - ep_ids
        if orphan_ids:
            issues.append(
                ValidationIssue(
                    field="samples",
                    message=(
                        f"{len(orphan_ids)} sample endpoint(s) absent from endpoint inventory"
                    ),
                )
            )
        if records.endpoints and not records.samples:
            issues.append(
                ValidationIssue(
                    field="samples",
                    message="Endpoints present but no metric samples; utilization findings will be weak",
                )
            )
        return issues

    def build_records(self) -> InferenceRecords:
        self.safety.check_action(Action(name="read_inference_inventory", is_read_only=True))
        records = InferenceRecords()
        for raw in self.endpoints_raw:
            endpoint = self._endpoint(raw)
            if endpoint is not None:
                records.endpoints.append(endpoint)
        for raw in self.samples_raw:
            sample = self._sample(raw)
            if sample is not None:
                records.samples.append(sample)
        return records

    def attach(self, dataset: ClusterDataset) -> ClusterDataset:
        records = self.build_records()
        dataset.endpoints = records.endpoints
        dataset.endpoint_samples = records.samples
        dataset.invalidate_indexes()
        return dataset

    def build_dataset(self) -> ClusterDataset:
        return self.attach(ClusterDataset())

    def _endpoint(self, raw: dict[str, Any]) -> InferenceEndpoint | None:
        endpoint_id = _pick(raw, "endpoint_id", "endpointId", "id", "deployment_name", "name")
        created = _parse_timestamp(_pick(raw, "created_at", "creationTimestamp", "created"))
        if endpoint_id is None or created is None:
            return None
        autoscaling = _as_bool(
            _pick(raw, "autoscaling_enabled", "autoscaling", "hpa_enabled", "auto_scale")
        )
        return InferenceEndpoint(
            endpoint_id=str(endpoint_id),
            name=str(_pick(raw, "name", "display_name", "deployment_name") or endpoint_id),
            model=str(_pick(raw, "model", "model_name", "modelName", "served_model") or ""),
            gpu_type=str(_pick(raw, "gpu_type", "gpuType", "accelerator", "gpu") or ""),
            replicas=_int_or(
                _pick(raw, "replicas", "replica_count", "desired_replicas", "scale"), 1
            ),
            gpus_per_replica=_int_or(
                _pick(raw, "gpus_per_replica", "gpu_count", "gpusPerReplica"),
                self.config.default_gpus_per_replica,
            ),
            gpu_ids=_str_list(_pick(raw, "gpu_ids", "gpuIds")),
            node_ids=_str_list(_pick(raw, "node_ids", "nodeIds", "nodes")),
            created_at=created,
            max_batch_size=_int_or(
                _pick(raw, "max_batch_size", "maxBatchSize", "batch_size"),
                self.config.default_max_batch_size,
            ),
            autoscaling_enabled=autoscaling if autoscaling is not None else False,
            min_replicas=_int_or(
                _pick(raw, "min_replicas", "minReplicas", "min_scale"), 1
            ),
            labels={str(k): str(v) for k, v in (raw.get("labels") or {}).items()},
        )

    def _sample(self, raw: dict[str, Any]) -> InferenceMetricSample | None:
        endpoint_id = _pick(raw, "endpoint_id", "endpointId", "id", "deployment_name")
        timestamp = _parse_timestamp(_pick(raw, "timestamp", "ts", "time", "collected_at"))
        if endpoint_id is None or timestamp is None:
            return None
        return InferenceMetricSample(
            endpoint_id=str(endpoint_id),
            timestamp=timestamp,
            requests_per_second=_float_or(
                _pick(raw, "requests_per_second", "rps", "qps", "throughput"), 0.0
            ),
            batch_size=_float_or(
                _pick(raw, "batch_size", "batchSize", "avg_batch_size"), 0.0
            ),
            p95_latency_ms=_float_or(
                _pick(raw, "p95_latency_ms", "p95_ms", "latency_p95", "latency_ms"), 0.0
            ),
            gpu_utilization_pct=_float_or(
                _pick(raw, "gpu_utilization_pct", "gpu_util", "gpu_utilization", "utilization"), 0.0
            ),
            replica_count=_int_or(
                _pick(raw, "replica_count", "replicas", "active_replicas"), 1
            ),
        )
