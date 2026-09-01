"""Read-only connector for capacity commitments.

A commitment is an accounting object, not a scheduler decision: it lives in a
billing export or a reservation inventory and never appears in cluster
telemetry. This connector normalizes such an export into `Commitment` records
and attaches them to a `ClusterDataset`. It reads. There is no code path here
that purchases, modifies, renews, or cancels anything.

Exports disagree on names — `reservation_id` vs `commitment_id`,
`instance_count` vs `quantity`, `effective_hourly_rate` vs `rate` — so parsing
goes through an alias table instead of one vendor's schema. Anything that
cannot be read is left at its neutral default rather than guessed, because the
commitment agent refuses to claim on a field it cannot prove.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from natilah.models.domain import ClusterDataset, ValidationIssue
from natilah.models.resources import Commitment

# Vendors spell the same three products a dozen ways; everything collapses to
# the three kinds `Commitment` already defines.
KIND_ALIASES: dict[str, str] = {
    "reserved": "reserved",
    "reserved_instance": "reserved",
    "reservation": "reserved",
    "ri": "reserved",
    "committed_use": "reserved",
    "cud": "reserved",
    "capacity_block": "reserved",
    "capacity_reservation": "reserved",
    "savings_plan": "savings_plan",
    "savingsplan": "savings_plan",
    "sp": "savings_plan",
    "compute_savings_plan": "savings_plan",
    "flexible_cud": "savings_plan",
    "spot": "spot",
    "spot_fleet": "spot",
    "preemptible": "spot",
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "commitment_id": (
        "commitment_id",
        "reservation_id",
        "subscription_id",
        "plan_id",
        "arn",
        "id",
    ),
    "kind": ("kind", "type", "offering_type", "purchase_type", "commitment_type", "plan_type"),
    "gpu_type": ("gpu_type", "accelerator_type", "instance_type", "machine_type", "sku"),
    "quantity": ("quantity", "gpu_count", "instance_count", "count", "units", "committed_gpus"),
    "hourly_rate": (
        "hourly_rate",
        "effective_hourly_rate",
        "committed_hourly_rate",
        "rate",
        "unit_price",
    ),
    "on_demand_rate": (
        "on_demand_rate",
        "list_hourly_rate",
        "public_rate",
        "demand_rate",
        "list_price",
    ),
    "start": ("start", "start_date", "start_time", "begin", "effective_date", "term_start"),
    "end": ("end", "end_date", "end_time", "expiry", "expires_at", "expiration_date", "term_end"),
    "auto_renew": ("auto_renew", "auto_renewal", "autorenew", "renew"),
    "scope": ("scope", "region", "zone", "account", "account_id", "project"),
    "labels": ("labels", "tags", "metadata"),
    "total_cost": ("total_cost", "upfront_cost", "commitment_total", "term_total", "upfront_fee"),
    "gpus_per_instance": ("gpus_per_instance", "gpus_per_unit", "accelerators_per_instance"),
}

TRUE_TOKENS = {"true", "yes", "y", "1", "on", "enabled", "auto"}


@dataclass
class CommitmentSourceConfig:
    """What the export does not say, and what to do about it."""

    source_name: str = "billing_export"
    default_kind: str = "reserved"
    default_gpu_type: str = ""
    default_scope: str = ""
    # Exports often price a whole instance; the meter is per GPU.
    gpus_per_instance: int = 1
    # Some exports quote only a term total. Spreading it evenly across the term
    # is arithmetic, not a guess, so it is allowed; inventing a rate is not.
    derive_hourly_from_total: bool = True
    # A reservation export rarely carries the public rate it was discounted
    # from. Without one the agent cannot price a premium, so it may be supplied
    # here rather than assumed from a catalog.
    on_demand_rates: dict[str, float] = field(default_factory=dict)
    drop_zero_quantity: bool = True


class CommitmentExportSource:
    """Reads commitment records out of a dict, a JSON file, or a list of rows.

    Deliberately not a `DataSource`: there is no commitment table to write to,
    and the ingestion interface exists to persist cluster telemetry. Commitments
    attach to an in-memory `ClusterDataset` instead, which is also what makes
    this testable with no billing API in reach.
    """

    def __init__(self, config: CommitmentSourceConfig | None = None):
        self.config = config or CommitmentSourceConfig()

    # ------------------------------------------------------------------ input

    @staticmethod
    def rows(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Accept `{"commitments": [...]}`, a bare list, or a single record."""
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("commitments", "reservations", "savings_plans", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        return [payload] if payload else []

    # ------------------------------------------------------------- validation

    def validate(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[ValidationIssue]:
        """Structural problems that would produce an unprovable commitment."""
        issues: list[ValidationIssue] = []
        rows = self.rows(payload)
        if not rows:
            issues.append(
                ValidationIssue(field="commitments", message="No commitment records found")
            )
            return issues
        seen: set[str] = set()
        for index, row in enumerate(rows):
            where = f"commitments[{index}]"
            identifier = _text(_pick(row, "commitment_id"))
            if not identifier:
                issues.append(ValidationIssue(field=where, message="Missing commitment identifier"))
            elif identifier in seen:
                issues.append(
                    ValidationIssue(field=where, message=f"Duplicate commitment id {identifier}")
                )
            else:
                seen.add(identifier)
            start = _as_datetime(_pick(row, "start"))
            end = _as_datetime(_pick(row, "end"))
            if start is None:
                issues.append(ValidationIssue(field=where, message="Missing or unparseable start"))
            if end is None:
                issues.append(ValidationIssue(field=where, message="Missing or unparseable end"))
            if start and end and end <= start:
                issues.append(ValidationIssue(field=where, message="Term ends at or before it starts"))
            if _as_float(_pick(row, "quantity"), 0.0) < 0:
                issues.append(ValidationIssue(field=where, message="Negative committed quantity"))
            if _as_float(_pick(row, "hourly_rate"), 0.0) < 0:
                issues.append(ValidationIssue(field=where, message="Negative hourly rate"))
        return issues

    # ---------------------------------------------------------------- loading

    def load(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[Commitment]:
        """Normalize an export. Rows that cannot be dated are dropped, not faked."""
        commitments: list[Commitment] = []
        for row in self.rows(payload):
            commitment = self._to_commitment(row)
            if commitment is not None:
                commitments.append(commitment)
        return commitments

    def load_file(self, path: str | Path) -> list[Commitment]:
        with Path(path).open("r", encoding="utf-8") as handle:
            return self.load(json.load(handle))

    def attach(
        self,
        dataset: ClusterDataset,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> ClusterDataset:
        """Merge commitments into a dataset, last write per id wins."""
        merged: dict[str, Commitment] = {c.commitment_id: c for c in dataset.commitments}
        for commitment in self.load(payload):
            merged[commitment.commitment_id] = commitment
        dataset.commitments = sorted(merged.values(), key=lambda c: (c.start, c.commitment_id))
        return dataset

    # --------------------------------------------------------------- internals

    def _to_commitment(self, row: dict[str, Any]) -> Commitment | None:
        identifier = _text(_pick(row, "commitment_id"))
        start = _as_datetime(_pick(row, "start"))
        end = _as_datetime(_pick(row, "end"))
        if not identifier or start is None or end is None or end <= start:
            return None

        per_instance = _as_int(_pick(row, "gpus_per_instance"), self.config.gpus_per_instance)
        quantity = _as_int(_pick(row, "quantity"), 0) * max(per_instance, 1)
        if quantity <= 0 and self.config.drop_zero_quantity:
            return None

        gpu_type = _text(_pick(row, "gpu_type")) or self.config.default_gpu_type
        hourly_rate = _as_float(_pick(row, "hourly_rate"), 0.0)
        if hourly_rate <= 0 and self.config.derive_hourly_from_total:
            hourly_rate = self._spread_total(row, start, end, quantity)

        on_demand = _as_float(_pick(row, "on_demand_rate"), 0.0)
        if on_demand <= 0:
            on_demand = self.config.on_demand_rates.get(gpu_type, 0.0)

        return Commitment(
            commitment_id=identifier,
            kind=self._kind(row),
            gpu_type=gpu_type,
            quantity=max(quantity, 0),
            hourly_rate=max(hourly_rate, 0.0),
            on_demand_rate=max(on_demand, 0.0),
            start=start,
            end=end,
            auto_renew=_as_bool(_pick(row, "auto_renew")),
            scope=_text(_pick(row, "scope")) or self.config.default_scope,
            labels=_as_labels(_pick(row, "labels")),
        )

    def _kind(self, row: dict[str, Any]) -> str:
        raw = _text(_pick(row, "kind")).lower().replace("-", "_").replace(" ", "_")
        return KIND_ALIASES.get(raw, self.config.default_kind)

    @staticmethod
    def _spread_total(
        row: dict[str, Any], start: datetime, end: datetime, quantity: int
    ) -> float:
        """A term total divided by the GPU-hours it buys is a rate, not a guess."""
        total = _as_float(_pick(row, "total_cost"), 0.0)
        hours = (end - start).total_seconds() / 3600.0
        if total <= 0 or hours <= 0 or quantity <= 0:
            return 0.0
        return total / (hours * quantity)


# ------------------------------------------------------------------- parsing


def _pick(row: dict[str, Any], field_name: str) -> Any:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for alias in FIELD_ALIASES.get(field_name, (field_name,)):
        if alias in lowered and lowered[alias] not in (None, ""):
            return lowered[alias]
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    parsed = _as_float(value, float(default))
    return int(round(parsed))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in TRUE_TOKENS


def _as_labels(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        labels: dict[str, str] = {}
        for item in value:
            if isinstance(item, dict) and "key" in item:
                labels[str(item["key"])] = str(item.get("value", ""))
        return labels
    return {}


def _as_datetime(value: Any) -> datetime | None:
    """ISO strings, epoch seconds, and datetimes, all normalized to UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = _text(value)
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
