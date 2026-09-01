"""Read-only network connector.

The GB-transferred meter has no single source: cross-zone bytes show up as VPC
flow logs on one cluster, a cloud billing export on the next, and a Prometheus
counter on the third, while image pulls arrive as kubelet `Pulled` events. This
connector normalizes any of those into `NetworkFlow` and `ImagePull` and does
nothing else. Every access is a read — file reads and HTTP GETs — and no method
here mutates a cluster, a registry, or a bill.

Network records have no persisted table yet, so the connector hands its output
to an in-memory `ClusterDataset` through `attach()` rather than pretending to
write them through `replace_cluster_data`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from natilah.models.domain import ClusterDataset, ValidationIssue
from natilah.models.resources import ImagePull, NetworkFlow

logger = logging.getLogger(__name__)

# A destination that is not a zone at all: the bytes left the provider.
EGRESS_ZONES = {"internet", "external", "public", "0.0.0.0/0", "wan"}

# Object stores are read across a zone boundary far more often than they are
# written, and they price differently from plain cross-AZ chatter.
STORAGE_HINTS = ("s3", "gcs", "gs://", "blob", "object", "minio", "nfs", "ceph", "lustre")

ZONE_LABEL_KEYS = (
    "zone",
    "topology.kubernetes.io/zone",
    "failure-domain.beta.kubernetes.io/zone",
    "availability_zone",
)

# kubelet says "already present on machine" for a cache hit and "Successfully
# pulled image ... in 12.3s" for a miss. That sentence is the only signal.
_CACHE_HIT_RE = re.compile(r"already present on machine", re.IGNORECASE)
_IMAGE_RE = re.compile(r"image[: ]+\"?([^\"\s]+)\"?", re.IGNORECASE)
_PULL_SECONDS_RE = re.compile(r"in ([0-9.]+)s")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _first(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    """Epoch seconds, epoch milliseconds, or ISO-8601 — flow logs use all three."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            return _parse_ts(float(text))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _zone_of(labels: Mapping[str, Any]) -> str:
    for key in ZONE_LABEL_KEYS:
        value = labels.get(key)
        if value:
            return str(value)
    return ""


def infer_kind(src_zone: str, dst_zone: str, hint: str = "", default: str = "cross_az") -> str:
    """Classify a flow when the source did not say. Cheapest plausible kind wins."""
    lowered = (hint or "").lower()
    if src_zone.lower() in EGRESS_ZONES or dst_zone.lower() in EGRESS_ZONES:
        return "egress"
    if any(token in lowered for token in STORAGE_HINTS):
        return "storage_read"
    if src_zone and dst_zone:
        return "intra_az" if src_zone == dst_zone else "cross_az"
    return default


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


@dataclass
class NetworkConnectorConfig:
    """Everything the connector needs that the raw records do not carry."""

    bytes_per_gb: float = 1e9
    min_flow_gb: float = 0.001  # counter noise, not traffic
    default_kind: str = "cross_az"
    node_zones: dict[str, str] = field(default_factory=dict)
    default_registry_zone: str = ""
    # Pull events carry no image size; without a size the agent refuses to claim.
    image_size_gb: dict[str, float] = field(default_factory=dict)
    drop_intra_az: bool = False


class NetworkDataSource:
    """Read-only network connector. Never issues a write of any kind."""

    source = "network"

    def __init__(
        self,
        *,
        flows_json: Sequence[Mapping[str, Any]] | None = None,
        pulls_json: Sequence[Mapping[str, Any]] | None = None,
        events_json: Sequence[Mapping[str, Any]] | None = None,
        nodes_json: Sequence[Mapping[str, Any]] | None = None,
        config: NetworkConnectorConfig | None = None,
    ):
        self.flows_json = list(flows_json or [])
        self.pulls_json = list(pulls_json or [])
        self.events_json = list(events_json or [])
        self.nodes_json = list(nodes_json or [])
        self.config = config or NetworkConnectorConfig()

    # -------------------------------------------------------------- loaders

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any], config: NetworkConnectorConfig | None = None
    ) -> "NetworkDataSource":
        """One dict in, records out — the path tests and JSON uploads both use."""
        return cls(
            flows_json=payload.get("flows") or payload.get("network_flows") or [],
            pulls_json=payload.get("image_pulls") or payload.get("pulls") or [],
            events_json=payload.get("events") or [],
            nodes_json=payload.get("nodes") or [],
            config=config,
        )

    @classmethod
    def from_json(
        cls, text: str, config: NetworkConnectorConfig | None = None
    ) -> "NetworkDataSource":
        return cls.from_mapping(json.loads(text), config=config)

    @classmethod
    def from_snapshot_dir(
        cls, directory: str | Path, config: NetworkConnectorConfig | None = None
    ) -> "NetworkDataSource":
        """Load from a directory of JSON dumps. Reads files, writes none."""
        path = Path(directory)
        payload: dict[str, Any] = {}
        for key, filename in (
            ("flows", "network_flows.json"),
            ("image_pulls", "image_pulls.json"),
            ("events", "events.json"),
            ("nodes", "nodes.json"),
        ):
            file = path / filename
            if not file.exists():
                continue
            data = json.loads(file.read_text(encoding="utf-8"))
            payload[key] = data.get("items", data) if isinstance(data, dict) else data
        return cls.from_mapping(payload, config=config)

    @classmethod
    async def from_prometheus(
        cls,
        prometheus_url: str,
        start: datetime,
        end: datetime,
        *,
        expr: str = "increase(container_network_transmit_bytes_total[1h])",
        step: int = 3600,
        config: NetworkConnectorConfig | None = None,
    ) -> "NetworkDataSource":
        """Range-query a byte counter. GET only; Prometheus is never written to."""
        import httpx

        base = prometheus_url.rstrip("/")
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(chunk_start + timedelta(days=1), end)
                params = {
                    "query": expr,
                    "start": str(int(chunk_start.timestamp())),
                    "end": str(int(chunk_end.timestamp())),
                    "step": str(step),
                }
                try:
                    resp = await client.get(f"{base}/api/v1/query_range", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    logger.warning("Prometheus flow query failed [%s-%s]", chunk_start, chunk_end)
                    chunk_start = chunk_end
                    continue
                for result in data.get("data", {}).get("result", []):
                    labels = result.get("metric", {})
                    owner = labels.get("pod") or labels.get("instance") or "flow"
                    for ts_val, raw in result.get("values", []):
                        rows.append(
                            {
                                "flow_id": f"{owner}-{int(float(ts_val))}",
                                "src_zone": labels.get("src_zone", labels.get("zone", "")),
                                "dst_zone": labels.get("dst_zone", ""),
                                "src_node_id": labels.get("node", labels.get("instance", "")),
                                "job_id": labels.get("job_id", labels.get("pod", "")),
                                "bytes": 0.0 if raw == "NaN" else float(raw),
                                "start": float(ts_val),
                                "end": float(ts_val) + step,
                            }
                        )
                chunk_start = chunk_end
        return cls(flows_json=rows, config=config)

    # ----------------------------------------------------------- validation

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.flows_json and not self.pulls_json and not self.events_json:
            issues.append(ValidationIssue(field="network", message="No flow or pull data provided"))
        unzoned = sum(
            1
            for row in self.flows_json
            if not _first(row, "src_zone", "source_zone", "srcZone")
            or not _first(row, "dst_zone", "destination_zone", "dstZone")
        )
        if unzoned:
            issues.append(
                ValidationIssue(
                    field="flows",
                    message=f"{unzoned} flow(s) missing a zone; billability cannot be proven",
                )
            )
        sized = [p for p in self.pulls_json if _to_float(_first(p, "gb", "size_gb", "bytes")) > 0]
        if self.pulls_json and not sized and not self.config.image_size_gb:
            issues.append(
                ValidationIssue(field="image_pulls", message="No pull reports an image size")
            )
        return issues

    # -------------------------------------------------------------- records

    def node_zones(self) -> dict[str, str]:
        """Node to zone, from config first and node labels second."""
        zones = dict(self.config.node_zones)
        for node in self.nodes_json:
            metadata = node.get("metadata", node)
            name = metadata.get("name") or node.get("node_id") or ""
            labels = metadata.get("labels", node.get("labels", {})) or {}
            zone = _zone_of(labels)
            if name and zone:
                zones.setdefault(str(name), zone)
        return zones

    def build_flows(self) -> list[NetworkFlow]:
        zones = self.node_zones()
        flows: list[NetworkFlow] = []
        for index, row in enumerate(self.flows_json):
            gb = _to_float(_first(row, "gb_transferred", "gb", "gigabytes"))
            if gb <= 0:
                raw_bytes = _to_float(_first(row, "bytes", "bytes_transferred", "octets"))
                gb = raw_bytes / self.config.bytes_per_gb if raw_bytes else 0.0
            if gb < self.config.min_flow_gb:
                continue
            src_node = _first(row, "src_node_id", "source_node", "src_node", "node", default=None)
            dst_node = _first(row, "dst_node_id", "destination_node", "dst_node", default=None)
            src_zone = str(
                _first(row, "src_zone", "source_zone", "srcZone", default="")
                or zones.get(str(src_node), "")
            )
            dst_zone = str(
                _first(row, "dst_zone", "destination_zone", "dstZone", default="")
                or zones.get(str(dst_node), "")
            )
            start = _parse_ts(_first(row, "start", "start_time", "start_ts", "timestamp"))
            end = _parse_ts(_first(row, "end", "end_time", "end_ts")) or start
            if start is None or end is None:
                continue
            hint = " ".join(
                str(_first(row, key, default="") or "")
                for key in ("service", "protocol", "endpoint", "path", "target")
            )
            kind = str(
                _first(row, "kind", "traffic_kind", "type", default="")
                or infer_kind(src_zone, dst_zone, hint, self.config.default_kind)
            )
            if self.config.drop_intra_az and kind == "intra_az" and src_zone == dst_zone:
                continue
            flows.append(
                NetworkFlow(
                    flow_id=str(_first(row, "flow_id", "id", default=f"flow-{index}")),
                    src_zone=src_zone,
                    dst_zone=dst_zone,
                    src_node_id=str(src_node) if src_node else None,
                    dst_node_id=str(dst_node) if dst_node else None,
                    job_id=str(_first(row, "job_id", "job", "pod", "workload", default="")) or None,
                    gb_transferred=gb,
                    start=start,
                    end=end,
                    kind=kind,
                )
            )
        return flows

    def build_image_pulls(self) -> list[ImagePull]:
        pulls = [self._pull_from_row(row, i) for i, row in enumerate(self.pulls_json)]
        return [p for p in pulls if p is not None] + self._pulls_from_events()

    def _pull_from_row(self, row: Mapping[str, Any], index: int) -> ImagePull | None:
        image = str(_first(row, "image", "image_name", default=""))
        node = str(_first(row, "node_id", "node", "host", "hostname", default=""))
        if not image or not node:
            return None
        gb = _to_float(_first(row, "gb", "size_gb"))
        if gb <= 0:
            raw_bytes = _to_float(_first(row, "bytes", "size_bytes"))
            gb = raw_bytes / self.config.bytes_per_gb if raw_bytes else 0.0
        if gb <= 0:
            gb = self.config.image_size_gb.get(image, 0.0)
        timestamp = _parse_ts(_first(row, "timestamp", "time", "ts", "start"))
        if timestamp is None:
            return None
        cached = _first(row, "cache_hit", "cached", default=None)
        return ImagePull(
            pull_id=str(_first(row, "pull_id", "id", default=f"pull-{index}")),
            node_id=node,
            image=image,
            gb=gb,
            timestamp=timestamp,
            job_id=str(_first(row, "job_id", "job", "pod", default="")) or None,
            cache_hit=bool(cached) if cached is not None else False,
            registry_zone=str(
                _first(row, "registry_zone", "registry", default=self.config.default_registry_zone)
            ),
            duration_seconds=_to_float(_first(row, "duration_seconds", "duration")),
        )

    def _pulls_from_events(self) -> list[ImagePull]:
        """kubelet Pulled events. The message text is the only cache signal."""
        zones = self.node_zones()
        pulls: list[ImagePull] = []
        for index, event in enumerate(self.events_json):
            if (event.get("reason") or "") != "Pulled":
                continue
            message = str(event.get("message") or "")
            match = _IMAGE_RE.search(message)
            if match is None:
                continue
            image = match.group(1).strip("\"")
            node = str(
                (event.get("source") or {}).get("host")
                or (event.get("involvedObject") or {}).get("name")
                or ""
            )
            timestamp = _parse_ts(
                event.get("lastTimestamp") or event.get("eventTime") or event.get("firstTimestamp")
            )
            if not node or timestamp is None:
                continue
            duration = _PULL_SECONDS_RE.search(message)
            pulls.append(
                ImagePull(
                    pull_id=str((event.get("metadata") or {}).get("uid") or f"event-pull-{index}"),
                    node_id=node,
                    image=image,
                    gb=self.config.image_size_gb.get(image, 0.0),
                    timestamp=timestamp,
                    job_id=(event.get("involvedObject") or {}).get("name"),
                    cache_hit=bool(_CACHE_HIT_RE.search(message)),
                    registry_zone=self.config.default_registry_zone or zones.get(node, ""),
                    duration_seconds=float(duration.group(1)) if duration else 0.0,
                )
            )
        return pulls

    # --------------------------------------------------------------- output

    def build_dataset(self) -> ClusterDataset:
        return ClusterDataset(flows=self.build_flows(), image_pulls=self.build_image_pulls())

    def attach(self, dataset: ClusterDataset) -> ClusterDataset:
        """Merge network records into a dataset another connector already built."""
        dataset.flows = [*dataset.flows, *self.build_flows()]
        dataset.image_pulls = [*dataset.image_pulls, *self.build_image_pulls()]
        dataset.invalidate_indexes()
        return dataset
