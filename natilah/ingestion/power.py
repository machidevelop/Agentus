"""Read-only power and thermal connector.

The electricity bill is the one cost in this platform that nothing else looks
at: schedulers account GPU-hours, finance accounts instance-hours, and the kWh
meter in the basement is watched by facilities, who never see the job trace.
This connector is the bridge — it normalizes three sources into the three
records the power agent reasons over:

    utility tariff sheet   ->  PowerTariff      (what a kWh costs, by hour)
    DCIM / facility export ->  FacilityProfile  (what the building adds, PUE)
    nvidia-smi clock query ->  ClockCap         (silicon that cannot run flat out)

It reads. It never sets a clock, never sets a power limit, never writes to a
DCIM system: every entry point here takes data that has already been exported,
and there is deliberately no code path that issues a command to hardware.

Persistence is by design absent. The Phase 3 records have no tables yet, so the
connector enriches a `ClusterDataset` in memory via `attach_to`, which is also
what makes it testable with a dict instead of a datacentre.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from natilah.models.domain import ClusterDataset
from natilah.models.resources import ClockCap, FacilityProfile, PowerTariff

logger = logging.getLogger(__name__)

# nvidia-smi reports throttle reasons as flags; only these mean the card is
# actually held below its rated clock rather than merely idling down.
THROTTLE_REASON_FIELDS: dict[str, str] = {
    "clocks_throttle_reasons.hw_thermal_slowdown": "hw_thermal_slowdown",
    "clocks_throttle_reasons.sw_thermal_slowdown": "sw_thermal_slowdown",
    "clocks_throttle_reasons.hw_power_brake_slowdown": "hw_power_brake",
    "clocks_throttle_reasons.sw_power_cap": "sw_power_cap",
    "clocks_event_reasons.hw_thermal_slowdown": "hw_thermal_slowdown",
    "clocks_event_reasons.sw_power_cap": "sw_power_cap",
}

_ACTIVE_FLAGS = {"active", "1", "true", "yes"}


def _parse_dt(value: Any) -> datetime | None:
    """Timestamps arrive as ISO strings, epoch seconds, or already parsed."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_mhz(value: Any) -> float | None:
    """`nvidia-smi --format=csv` emits "1215 MHz"; JSON exports emit 1215."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().removesuffix("mhz").strip()
    if not text or text in {"n/a", "[n/a]", "not supported"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _throttle_reason(raw: dict[str, Any]) -> str:
    reasons = [
        label
        for key, label in THROTTLE_REASON_FIELDS.items()
        if str(raw.get(key, "")).strip().lower() in _ACTIVE_FLAGS
    ]
    if reasons:
        return ",".join(sorted(set(reasons)))
    return str(raw.get("reason", "") or "").strip()


@dataclass
class PowerConnectorConfig:
    """Defaults for fields a given export happens not to carry."""

    default_price_per_kwh: float = 0.12
    default_pue: float = 1.4
    default_zone: str = ""
    # Below this the cap is measurement noise or a normal idle downclock.
    min_throttle_fraction: float = 0.03
    # A PUE under 1.0 is physically impossible and over this is a bad export.
    max_pue: float = 3.0


@dataclass
class PowerTelemetry:
    """Normalized power records plus whatever the export got wrong."""

    tariffs: list[PowerTariff] = field(default_factory=list)
    facilities: list[FacilityProfile] = field(default_factory=list)
    clock_caps: list[ClockCap] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    source: str = "power"

    def attach_to(self, dataset: ClusterDataset) -> ClusterDataset:
        """Merge into a dataset in place. Additive: other connectors keep theirs."""
        dataset.tariffs.extend(self.tariffs)
        dataset.facilities.extend(self.facilities)
        dataset.clock_caps.extend(self.clock_caps)
        dataset.invalidate_indexes()
        return dataset


class PowerConnector:
    """Read-only loader for tariff, facility, and clock-cap exports.

    Accepts an already-exported payload (dict or JSON file). Nothing in this
    class opens a session to hardware, so there is no writable surface to
    misuse — a live DCIM poller would sit in front of it and hand it the same
    dict.
    """

    def __init__(self, config: PowerConnectorConfig | None = None):
        self.config = config or PowerConnectorConfig()

    # -------------------------------------------------------------- entry points

    def load(self, payload: dict[str, Any]) -> PowerTelemetry:
        issues: list[str] = []
        tariffs = self._tariffs(payload.get("tariffs") or [], issues)
        facilities = self._facilities(payload.get("facilities") or [], issues)
        caps = self._clock_caps(payload.get("clock_caps") or [], issues)
        caps.extend(
            self.parse_nvidia_smi_clocks(
                payload.get("nvidia_smi_clocks") or [],
                window_start=_parse_dt(payload.get("window_start")),
                window_end=_parse_dt(payload.get("window_end")),
                issues=issues,
            )
        )
        return PowerTelemetry(
            tariffs=tariffs,
            facilities=facilities,
            clock_caps=caps,
            issues=issues,
            source=str(payload.get("source") or "power"),
        )

    def load_json(self, path: str | Path) -> PowerTelemetry:
        with open(path, "r", encoding="utf-8") as handle:
            return self.load(json.load(handle))

    def ingest_into(self, dataset: ClusterDataset, payload: dict[str, Any]) -> PowerTelemetry:
        telemetry = self.load(payload)
        telemetry.attach_to(dataset)
        return telemetry

    # ------------------------------------------------------------------ parsers

    def _tariffs(self, rows: list[dict[str, Any]], issues: list[str]) -> list[PowerTariff]:
        parsed: list[PowerTariff] = []
        explicit_peak: list[bool] = []
        for raw in rows:
            start_hour = int(raw.get("start_hour", 0) or 0)
            end_hour = int(raw.get("end_hour", 24) or 24)
            if not 0 <= start_hour < end_hour <= 24:
                issues.append(f"tariff window {start_hour}-{end_hour} is not a valid hour range")
                continue
            price = float(raw.get("price_per_kwh", self.config.default_price_per_kwh) or 0.0)
            if price <= 0:
                issues.append(f"tariff for zone {raw.get('zone', '')!r} has a non-positive price")
                continue
            parsed.append(
                PowerTariff(
                    zone=str(raw.get("zone", self.config.default_zone) or ""),
                    start_hour=start_hour,
                    end_hour=end_hour,
                    price_per_kwh=price,
                    is_peak=bool(raw.get("is_peak", False)),
                )
            )
            explicit_peak.append("is_peak" in raw)
        self._infer_peak(parsed, explicit_peak)
        return parsed

    def _infer_peak(self, tariffs: list[PowerTariff], explicit: list[bool]) -> None:
        """A utility sheet often names windows, not peaks. Cheapest hour wins.

        Marking peaks by price rather than by label keeps the agent's rate
        delta anchored to what is actually billed.
        """
        cheapest: dict[str, float] = {}
        for tariff in tariffs:
            current = cheapest.get(tariff.zone)
            if current is None or tariff.price_per_kwh < current:
                cheapest[tariff.zone] = tariff.price_per_kwh
        for tariff, was_explicit in zip(tariffs, explicit):
            if was_explicit:
                continue
            tariff.is_peak = tariff.price_per_kwh > cheapest.get(tariff.zone, tariff.price_per_kwh)

    def _facilities(self, rows: list[dict[str, Any]], issues: list[str]) -> list[FacilityProfile]:
        parsed: list[FacilityProfile] = []
        for raw in rows:
            pue = float(raw.get("pue", self.config.default_pue) or self.config.default_pue)
            if pue < 1.0 or pue > self.config.max_pue:
                issues.append(f"facility {raw.get('zone', '')!r} reports an implausible PUE {pue}")
                continue
            node_ids = [str(n) for n in (raw.get("node_ids") or []) if str(n)]
            if not node_ids:
                issues.append(f"facility {raw.get('zone', '')!r} covers no nodes; PUE cannot be applied")
            parsed.append(
                FacilityProfile(
                    zone=str(raw.get("zone", self.config.default_zone) or ""),
                    pue=pue,
                    node_ids=node_ids,
                    carbon_kg_per_kwh=float(raw.get("carbon_kg_per_kwh", 0.0) or 0.0),
                )
            )
        return parsed

    def _clock_caps(self, rows: list[dict[str, Any]], issues: list[str]) -> list[ClockCap]:
        parsed: list[ClockCap] = []
        for raw in rows:
            cap = self._clock_cap(raw, _parse_dt(raw.get("start")), _parse_dt(raw.get("end")), issues)
            if cap is not None:
                parsed.append(cap)
        return parsed

    def parse_nvidia_smi_clocks(
        self,
        rows: list[dict[str, Any]],
        window_start: datetime | None,
        window_end: datetime | None,
        issues: list[str] | None = None,
    ) -> list[ClockCap]:
        """Turn a `--query-gpu=clocks.sm,clocks.max.sm,...` export into caps.

        The query is an instantaneous read, so the caller supplies the window
        over which that reading is taken to hold. Without one there is no
        duration and therefore no energy to attribute, so the row is dropped.
        """
        issues = issues if issues is not None else []
        if not rows:
            return []
        if window_start is None or window_end is None:
            issues.append("nvidia-smi clock rows supplied without a window; no duration to attribute")
            return []
        parsed: list[ClockCap] = []
        for raw in rows:
            cap = self._clock_cap(raw, window_start, window_end, issues)
            if cap is not None:
                parsed.append(cap)
        return parsed

    def _clock_cap(
        self,
        raw: dict[str, Any],
        start: datetime | None,
        end: datetime | None,
        issues: list[str],
    ) -> ClockCap | None:
        gpu_id = str(raw.get("gpu_id") or raw.get("uuid") or raw.get("index") or "").strip()
        if not gpu_id:
            issues.append("clock cap row has no gpu identifier")
            return None
        capped = _parse_mhz(raw.get("capped_mhz", raw.get("clocks.sm", raw.get("clocks_sm"))))
        maximum = _parse_mhz(raw.get("max_mhz", raw.get("clocks.max.sm", raw.get("clocks_max_sm"))))
        if capped is None or maximum is None or maximum <= 0:
            issues.append(f"clock cap for {gpu_id} is missing a usable clock pair")
            return None
        if start is None or end is None or end <= start:
            issues.append(f"clock cap for {gpu_id} has no positive duration")
            return None
        cap = ClockCap(
            gpu_id=gpu_id,
            capped_mhz=capped,
            max_mhz=maximum,
            start=start,
            end=end,
            reason=_throttle_reason(raw),
        )
        if cap.throttle_fraction < self.config.min_throttle_fraction:
            return None
        return cap
