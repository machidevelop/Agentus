"""Power-efficiency agent.

Objective: the kWh meter. Not GPU-hours seen from a different angle.

Every other agent in the fleet argues about who should have held a GPU. This
one never does. It reads the same telemetry to answer a question nobody in the
system is currently asking — how much electricity the fleet burned, and how
much of it bought nothing — and claims only in kilowatt-hours, so its findings
can never cancel or duplicate a scheduling claim in the ledger.

Three conditions, three ways the meter spins for nothing:

    capped clocks   silicon held below its rated clock takes longer to finish
                    the same work, so the card and the cooling behind it burn
                    their standing draw for hours that did not need to exist
    PUE placement   identical work in a building with worse overhead, where a
                    better one had the capacity to host it
    off-peak shift  a deferrable job run against the expensive half of the
                    utility's tariff sheet, when the cheap half was open

The energy model is deliberately pessimistic about itself: measured
`power_watts` where it exists, TDP x utilization where it does not with
confidence dropped hard for saying so, and a claim that can never exceed what
the hardware could physically have drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.domain import (
    ClusterDataset,
    GPUUtilizationSample,
    Job,
    ResourceClaim,
    ResourceInterval,
    gpu_type_matches,
    resolve_gpu_type,
)
from natilah.models.enums import AgentObjective, Meter, OpportunityType
from natilah.models.resources import ClockCap, FacilityProfile, PowerTariff

# A GPU below this is coasting; a cap on a coasting card costs nothing extra.
ACTIVE_PCT = 20.0

# Caps under this are idle downclocking or measurement noise, not a limit.
MIN_THROTTLE_FRACTION = 0.05
MIN_CAP_MINUTES = 30.0

# The share of a GPU's draw that does not scale with useful work: memory
# refresh, leakage, fans, board overhead. Only this part, plus the facility
# overhead on it, is genuinely wasted when a throttle stretches a job — the
# dynamic part does the same number of operations either way. Deliberately at
# the low end of the published range so the claim errs downward.
STATIC_POWER_FRACTION = 0.35

# Below this the claimed window is not actually instrumented.
MIN_TELEMETRY_COVERAGE = 0.5

# Confidence ceiling when energy is inferred from TDP instead of measured.
TDP_FALLBACK_COMPLETENESS = 0.4

MIN_PUE_DELTA = 0.05
MIN_KWH = 0.01

# A long job cannot be slid across a tariff boundary without changing when its
# results land, so only short work is treated as deferrable.
MAX_DEFERRABLE_HOURS = 8.0
DEFERRABLE_PRIORITY_MAX = 0

DEADLINE_KEYS = frozenset(
    {"deadline", "deadline_utc", "due_by", "due_at", "sla", "start_before", "must_start_by"}
)
FALSEY = {"false", "no", "0", "off"}
TRUTHY = {"true", "yes", "1", "on"}

JOULES_PER_KWH = 3_600_000.0


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class EnergyWindow:
    """Energy drawn by one GPU over one window, and how much to trust it."""

    gpu_id: str
    start: datetime
    end: datetime
    kwh_it: float
    pue: float
    mean_watts: float
    measured: bool
    coverage: float
    active_fraction: float
    sample_count: int

    @property
    def hours(self) -> float:
        return _hours(self.start, self.end)

    @property
    def kwh_facility(self) -> float:
        """What the utility meter sees: IT draw plus the building's overhead."""
        return self.kwh_it * self.pue

    @property
    def completeness(self) -> float:
        base = 1.0 if self.measured else TDP_FALLBACK_COMPLETENESS
        return round(base * (0.5 + 0.5 * min(1.0, self.coverage)), 4)


class PowerEfficiencyAgent(ResourceAgent):
    name = "power_efficiency_agent"
    objective = AgentObjective.POWER_EFFICIENCY
    primary_meter = Meter.KWH
    signal_types = (
        OpportunityType.CAPPED_CLOCKS,
        OpportunityType.PUE_PLACEMENT,
        OpportunityType.OFF_PEAK_SHIFT,
    )
    finding_title = "Power and thermal waste"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cached_for: ClusterDataset | None = None
        self._samples: dict[str, list[GPUUtilizationSample]] = {}
        self._facility_by_node: dict[str, FacilityProfile] = {}

    # ------------------------------------------------------------ energy model

    def energy(
        self, dataset: ClusterDataset, gpu_id: str, start: datetime, end: datetime
    ) -> EnergyWindow:
        """kWh drawn by one GPU between two instants.

        Measured `power_watts` is integrated trapezoidally over the span it
        covers and extended at its own mean across whatever it does not; when
        no sample carries power at all, the fallback is TDP x utilization,
        which understates a real card (it ignores the idle floor) and is
        reported with `measured=False` so confidence drops for it.
        """
        self._prime(dataset)
        pue = self._pue_for_gpu(dataset, gpu_id)
        window_seconds = max(0.0, (end - start).total_seconds())
        samples = [s for s in self._samples.get(gpu_id, []) if start <= s.timestamp <= end]
        blank = EnergyWindow(
            gpu_id=gpu_id,
            start=start,
            end=end,
            kwh_it=0.0,
            pue=pue,
            mean_watts=0.0,
            measured=False,
            coverage=0.0,
            active_fraction=0.0,
            sample_count=0,
        )
        if window_seconds <= 0 or not samples:
            return blank

        active_fraction = sum(
            1 for s in samples if s.gpu_utilization_pct >= ACTIVE_PCT
        ) / len(samples)
        powered = [s for s in samples if s.power_watts is not None]

        if len(powered) >= 2:
            joules = 0.0
            for left, right in zip(powered, powered[1:]):
                seconds = (right.timestamp - left.timestamp).total_seconds()
                joules += 0.5 * (float(left.power_watts) + float(right.power_watts)) * seconds
            span = (powered[-1].timestamp - powered[0].timestamp).total_seconds()
            mean_watts = joules / span if span > 0 else 0.0
            joules += mean_watts * max(0.0, window_seconds - span)
            return EnergyWindow(
                gpu_id=gpu_id,
                start=start,
                end=end,
                kwh_it=joules / JOULES_PER_KWH,
                pue=pue,
                mean_watts=mean_watts,
                measured=True,
                coverage=min(1.0, span / window_seconds),
                active_fraction=active_fraction,
                sample_count=len(samples),
            )

        # No usable power series. Utilization against the card's rated TDP is
        # the only thing left, and it is a floor rather than an estimate.
        tdp = self._tdp_watts(dataset, gpu_id)
        mean_util = sum(s.gpu_utilization_pct for s in samples) / len(samples) / 100.0
        mean_watts = tdp * max(0.0, min(1.0, mean_util))
        span = (samples[-1].timestamp - samples[0].timestamp).total_seconds()
        return EnergyWindow(
            gpu_id=gpu_id,
            start=start,
            end=end,
            kwh_it=mean_watts * window_seconds / 3600.0 / 1000.0,
            pue=pue,
            mean_watts=mean_watts,
            measured=False,
            coverage=min(1.0, span / window_seconds),
            active_fraction=active_fraction,
            sample_count=len(samples),
        )

    def energy_for_gpus(
        self, dataset: ClusterDataset, gpu_ids: list[str], start: datetime, end: datetime
    ) -> list[EnergyWindow]:
        return [self.energy(dataset, gpu_id, start, end) for gpu_id in gpu_ids]

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        self._cached_for = None
        self._prime(dataset)
        window = self._window(dataset)
        if window is None:
            return []
        return [
            *self._detect_capped_clocks(dataset),
            *self._detect_pue_placement(dataset, window),
            *self._detect_off_peak(dataset),
        ]

    def _detect_capped_clocks(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        reasons = [c.reason for c in dataset.clock_caps if c.throttle_fraction >= MIN_THROTTLE_FRACTION]
        for cap in dataset.clock_caps:
            throttle = cap.throttle_fraction
            hours = _hours(cap.start, cap.end)
            if throttle < MIN_THROTTLE_FRACTION or hours * 60.0 < MIN_CAP_MINUTES:
                continue
            energy = self.energy(dataset, cap.gpu_id, cap.start, cap.end)
            # Work stretched by the throttle: at clock fraction f the same work
            # occupies the card 1/f as long, so the surplus time is the window's
            # active share x the throttle fraction.
            extra_hours = hours * energy.active_fraction * throttle
            overhead_kwh = (
                energy.mean_watts * STATIC_POWER_FRACTION * extra_hours * energy.pue / 1000.0
            )
            observations.append(
                ResourceObservation(
                    observation_id=f"capped_clocks:{cap.gpu_id}:{cap.start.isoformat()}",
                    signal_type=OpportunityType.CAPPED_CLOCKS,
                    resource_id=cap.gpu_id,
                    timestamp=cap.start,
                    severity=round(min(1.0, throttle * 2.0), 4),
                    description=(
                        f"GPU {cap.gpu_id} ran at {cap.capped_mhz:.0f} MHz against a rated "
                        f"{cap.max_mhz:.0f} MHz for {hours:.1f}h ({throttle:.0%} throttle"
                        f"{', ' + cap.reason if cap.reason else ''}), stretching the same work "
                        f"and holding {energy.mean_watts:.0f} W of standing draw open longer."
                    ),
                    affected_gpu_ids=[cap.gpu_id],
                    affected_job_ids=self._job_ids_on(dataset, [cap.gpu_id], cap.start, cap.end),
                    evidence=self._energy_evidence(
                        [energy],
                        cap_gpu_ids=[cap.gpu_id],
                        cap_hours=hours,
                        cap_pue=energy.pue,
                        window_start=cap.start,
                        window_end=cap.end,
                        throttle_fraction=throttle,
                        capped_mhz=cap.capped_mhz,
                        rated_mhz=cap.max_mhz,
                        cap_reason=cap.reason,
                        extra_hours=round(extra_hours, 4),
                        overhead_kwh=round(overhead_kwh, 6),
                        static_power_fraction=STATIC_POWER_FRACTION,
                        signal_reason=(
                            f"{throttle:.0%} clock cap over {hours:.1f}h with "
                            f"{energy.active_fraction:.0%} of samples showing active work"
                        ),
                    ),
                    data_completeness=energy.completeness,
                    signal_strength=round(min(1.0, throttle / 0.3), 4),
                    recurrence=max(0, sum(1 for r in reasons if r == cap.reason) - 1),
                )
            )
        return observations

    def _detect_pue_placement(
        self, dataset: ClusterDataset, window: tuple[datetime, datetime]
    ) -> list[ResourceObservation]:
        facilities = [f for f in dataset.facilities if f.node_ids]
        if len(facilities) < 2:
            return []
        ranked = sorted(facilities, key=lambda f: f.pue)
        best = ranked[0]
        start, end = window
        observations: list[ResourceObservation] = []
        for facility in facilities:
            delta = facility.pue - best.pue
            if delta < MIN_PUE_DELTA:
                continue
            targets = [f.zone for f in ranked if f.pue < facility.pue - MIN_PUE_DELTA]
            for node_id in facility.node_ids:
                gpu_ids = sorted(g.gpu_id for g in dataset.gpus if g.node_id == node_id)
                if not gpu_ids:
                    continue
                energies = self.energy_for_gpus(dataset, gpu_ids, start, end)
                it_kwh = sum(e.kwh_it for e in energies)
                if it_kwh <= MIN_KWH or not any(e.active_fraction > 0 for e in energies):
                    continue
                observations.append(
                    ResourceObservation(
                        observation_id=f"pue_placement:{node_id}",
                        signal_type=OpportunityType.PUE_PLACEMENT,
                        resource_id=node_id,
                        timestamp=start,
                        severity=round(min(1.0, delta / 0.5), 4),
                        description=(
                            f"Node {node_id} did {it_kwh:.1f} kWh of IT work in {facility.zone} "
                            f"(PUE {facility.pue:.2f}) over {_hours(start, end):.1f}h, while "
                            f"{best.zone} runs the same work at PUE {best.pue:.2f}."
                        ),
                        affected_gpu_ids=gpu_ids,
                        affected_job_ids=self._job_ids_on(dataset, gpu_ids, start, end),
                        evidence=self._energy_evidence(
                            energies,
                            cap_gpu_ids=gpu_ids,
                            cap_hours=_hours(start, end),
                            cap_pue=facility.pue,
                            window_start=start,
                            window_end=end,
                            node_id=node_id,
                            source_zone=facility.zone,
                            source_pue=facility.pue,
                            target_zone=best.zone,
                            target_pue=best.pue,
                            target_zones=targets,
                            it_kwh=round(it_kwh, 6),
                            pue_delta=round(delta, 4),
                            signal_reason=(
                                f"PUE {facility.pue:.2f} vs {best.pue:.2f} available in "
                                f"{best.zone} over the same window"
                            ),
                        ),
                        data_completeness=min(e.completeness for e in energies),
                        signal_strength=round(min(1.0, delta / 0.4), 4),
                        recurrence=max(0, len(facility.node_ids) - 1),
                    )
                )
        return observations

    def _detect_off_peak(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        if not dataset.tariffs:
            return []
        deferrable = [j for j in dataset.jobs if self._deferrable_reason(j) is None]
        observations: list[ResourceObservation] = []
        for job in deferrable:
            gpu_ids = self._gpu_ids_for_job(dataset, job)
            if not gpu_ids or job.start_time is None or job.end_time is None:
                continue
            zone = self._zone_for_gpu(dataset, gpu_ids[0])
            tariffs = self._tariffs_for_zone(dataset, zone)
            if not tariffs:
                continue
            segments = self._peak_segments(tariffs, job.start_time, job.end_time)
            off_peak = sorted(
                (t for t in tariffs if not t.is_peak), key=lambda t: t.price_per_kwh
            )
            if not segments or not off_peak:
                continue

            peak_kwh = 0.0
            peak_cost = 0.0
            energies: list[EnergyWindow] = []
            segment_records: list[dict] = []
            for seg_start, seg_end, tariff in segments:
                seg_energies = self.energy_for_gpus(dataset, gpu_ids, seg_start, seg_end)
                seg_kwh = sum(e.kwh_facility for e in seg_energies)
                if seg_kwh <= 0:
                    continue
                energies.extend(seg_energies)
                peak_kwh += seg_kwh
                peak_cost += seg_kwh * tariff.price_per_kwh
                segment_records.append(
                    {
                        "start": seg_start.isoformat(),
                        "end": seg_end.isoformat(),
                        "price_per_kwh": tariff.price_per_kwh,
                        "kwh": round(seg_kwh, 6),
                    }
                )
            if peak_kwh <= MIN_KWH or not energies:
                continue

            peak_rate = peak_cost / peak_kwh
            longest_off_peak = self._longest_off_peak_hours(tariffs)
            run_hours = _hours(job.start_time, job.end_time)
            observations.append(
                ResourceObservation(
                    observation_id=f"off_peak_shift:{job.job_id}",
                    signal_type=OpportunityType.OFF_PEAK_SHIFT,
                    resource_id=job.job_id,
                    timestamp=job.start_time,
                    severity=round(
                        min(1.0, (peak_rate - off_peak[0].price_per_kwh) / max(peak_rate, 1e-9)), 4
                    ),
                    description=(
                        f"Deferrable job {job.job_id} drew {peak_kwh:.1f} kWh on {len(gpu_ids)} "
                        f"GPU(s) during peak tariff hours in zone {zone or 'default'} at "
                        f"${peak_rate:.4f}/kWh, while an off-peak window of "
                        f"{longest_off_peak:.0f}h at ${off_peak[0].price_per_kwh:.4f}/kWh was open."
                    ),
                    affected_gpu_ids=gpu_ids,
                    affected_job_ids=[job.job_id],
                    evidence=self._energy_evidence(
                        energies,
                        cap_gpu_ids=gpu_ids,
                        cap_hours=sum(_hours(s, e) for s, e, _ in segments),
                        cap_pue=max(e.pue for e in energies),
                        window_start=job.start_time,
                        window_end=job.end_time,
                        job_id=job.job_id,
                        zone=zone,
                        peak_kwh=round(peak_kwh, 6),
                        peak_rate=round(peak_rate, 6),
                        off_peak_rates=[t.price_per_kwh for t in off_peak],
                        off_peak_window_hours=longest_off_peak,
                        run_hours=round(run_hours, 4),
                        peak_segments=segment_records,
                        signal_reason=(
                            f"{peak_kwh:.1f} kWh billed at peak against an available "
                            f"${off_peak[0].price_per_kwh:.4f}/kWh off-peak rate"
                        ),
                    ),
                    data_completeness=min(e.completeness for e in energies),
                    signal_strength=round(
                        min(1.0, (peak_rate - off_peak[0].price_per_kwh) / max(peak_rate, 1e-9) * 2),
                        4,
                    ),
                    recurrence=max(0, len(deferrable) - 1),
                )
            )
        return observations

    # -------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.CAPPED_CLOCKS:
            return self._clock_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.PUE_PLACEMENT:
            return self._pue_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.OFF_PEAK_SHIFT:
            return self._off_peak_candidates(dataset, observation)
        return []

    def _clock_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        start, end = self._evidence_window(ev)
        gpu_id = observation.resource_id
        overhead = float(ev.get("overhead_kwh") or 0.0)
        if start is None or end is None or overhead <= 0:
            return []
        reason = ev.get("cap_reason") or "an unrecorded cause"
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="clear_clock_cap",
                description=(
                    f"Clear the {float(ev['throttle_fraction']):.0%} clock cap on {gpu_id} at its "
                    f"root cause ({reason}) so the same work occupies the card "
                    f"{float(ev['extra_hours']):.1f}h less."
                ),
                proposed_action={
                    "kind": "clear_clock_cap",
                    "gpu_id": gpu_id,
                    "cap_reason": reason,
                    "observed_capped_mhz": ev.get("capped_mhz"),
                    "rated_mhz": ev.get("rated_mhz"),
                    "restored_fraction": 1.0,
                    "recovered_kwh": round(overhead, 6),
                },
                rationale=(
                    "Clock-limited work runs longer for the same result, so the card's standing "
                    "draw and the cooling behind it are billed for hours that buy nothing."
                ),
                source="detector:clock_cap:full_restore",
                claim=self._claim(
                    [self._interval(gpu_id, start, end, overhead)],
                    basis=(
                        f"Static-draw energy ({STATIC_POWER_FRACTION:.0%} of a measured "
                        f"{float(ev['mean_watts']):.0f} W) burned over the "
                        f"{float(ev['extra_hours']):.2f}h the {float(ev['throttle_fraction']):.0%} "
                        f"throttle added to active work, grossed up by PUE {float(ev['cap_pue']):.2f}."
                    ),
                ),
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="partial_clock_restore",
                description=(
                    f"Recover half the clock headroom on {gpu_id} — the outcome if {reason} is "
                    "only partly addressable (airflow, ambient, or a power budget kept in place)."
                ),
                proposed_action={
                    "kind": "clear_clock_cap",
                    "gpu_id": gpu_id,
                    "cap_reason": reason,
                    "restored_fraction": 0.5,
                    "recovered_kwh": round(overhead * 0.5, 6),
                },
                rationale=(
                    "A conservative floor on the same condition: half the throttle removed "
                    "recovers half the stretched runtime, with no assumption that the cap can be "
                    "fully lifted."
                ),
                source="detector:clock_cap:partial_restore",
                claim=self._claim(
                    [self._interval(gpu_id, start, end, overhead * 0.5)],
                    basis="Half the modelled throttle overhead, for a partial fix.",
                ),
            )
        )

        peer = self._unthrottled_peer(dataset, gpu_id, start, end)
        if peer:
            candidates.append(
                ResourceCandidate(
                    kind="relocate_to_unthrottled_peer",
                    description=(
                        f"Run this work on {peer}, an identical uncapped GPU, instead of the "
                        f"throttled {gpu_id}."
                    ),
                    proposed_action={
                        "kind": "relocate_to_unthrottled_peer",
                        "gpu_id": gpu_id,
                        "peer_gpu_id": peer,
                        "recovered_kwh": round(overhead, 6),
                    },
                    rationale=(
                        "The fleet already holds an uncapped card of the same type that was free "
                        "for the window, so the stretched runtime was avoidable without touching "
                        "the throttled card at all."
                    ),
                    source="detector:clock_cap:peer_gpu",
                    claim=self._claim(
                        [self._interval(gpu_id, start, end, overhead)],
                        basis="Throttle overhead avoided by running on an uncapped GPU.",
                    ),
                )
            )
        return candidates

    def _pue_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        start, end = self._evidence_window(ev)
        if start is None or end is None:
            return []
        gpu_ids = list(ev.get("cap_gpu_ids") or [])
        it_kwh = float(ev.get("it_kwh") or 0.0)
        source_pue = float(ev.get("source_pue") or 1.0)
        node_id = str(ev.get("node_id") or observation.resource_id)
        by_zone = {f.zone: f for f in dataset.facilities if f.node_ids}
        candidates: list[ResourceCandidate] = []

        for rank, zone in enumerate(list(ev.get("target_zones") or [])[:2]):
            target = by_zone.get(zone)
            if target is None:
                continue
            delta = source_pue - target.pue
            saving = it_kwh * delta
            candidates.append(
                ResourceCandidate(
                    kind="relocate_workload",
                    description=(
                        f"Host node {node_id}'s work in {zone} (PUE {target.pue:.2f}) instead of "
                        f"{ev.get('source_zone')} (PUE {source_pue:.2f})."
                    ),
                    proposed_action={
                        "kind": "relocate_workload",
                        "from_node_id": node_id,
                        "from_zone": ev.get("source_zone"),
                        "to_zone": zone,
                        "gpu_ids": gpu_ids,
                        "gpu_count": len(gpu_ids),
                        "pue_delta": round(delta, 4),
                        "recovered_kwh": round(saving, 6),
                    },
                    rationale=(
                        "The IT energy is identical in either building; only the overhead the "
                        "building adds to it differs, and the cheaper building had free capacity "
                        "of the same GPU type for the whole window."
                    ),
                    source=f"detector:pue:rank_{rank}",
                    claim=self._claim(
                        self._per_gpu_intervals(dataset, gpu_ids, start, end, delta),
                        basis=(
                            f"{it_kwh:.2f} kWh of IT energy x a PUE delta of {delta:.2f} between "
                            f"{ev.get('source_zone')} and {zone}."
                        ),
                    ),
                )
            )

        target_zone = str(ev.get("target_zone") or "")
        target = by_zone.get(target_zone)
        if target is not None and len(gpu_ids) >= 2:
            half = gpu_ids[: len(gpu_ids) // 2]
            delta = source_pue - target.pue
            candidates.append(
                ResourceCandidate(
                    kind="relocate_partial",
                    description=(
                        f"Host {len(half)} of node {node_id}'s {len(gpu_ids)} GPUs in "
                        f"{target_zone}, leaving the rest in place."
                    ),
                    proposed_action={
                        "kind": "relocate_workload",
                        "from_node_id": node_id,
                        "from_zone": ev.get("source_zone"),
                        "to_zone": target_zone,
                        "gpu_ids": half,
                        "gpu_count": len(half),
                        "pue_delta": round(delta, 4),
                    },
                    rationale=(
                        "A partial move needs only half the free capacity in the target facility "
                        "and recovers the overhead on the half that moves."
                    ),
                    source="detector:pue:partial",
                    claim=self._claim(
                        self._per_gpu_intervals(dataset, half, start, end, delta),
                        basis=f"PUE delta {delta:.2f} applied to {len(half)} relocated GPU(s).",
                    ),
                )
            )
        return candidates

    def _off_peak_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        job_id = str(ev.get("job_id") or observation.resource_id)
        gpu_ids = list(ev.get("cap_gpu_ids") or [])
        segments = list(ev.get("peak_segments") or [])
        rates = list(ev.get("off_peak_rates") or [])
        peak_rate = float(ev.get("peak_rate") or 0.0)
        if not segments or not rates:
            return []

        candidates: list[ResourceCandidate] = []
        for rank, off_rate in enumerate(rates[:2]):
            delta = peak_rate - float(off_rate)
            if delta <= 0:
                continue
            candidates.append(
                ResourceCandidate(
                    kind="defer_to_off_peak",
                    description=(
                        f"Run {job_id} in the ${float(off_rate):.4f}/kWh off-peak window instead "
                        f"of the ${peak_rate:.4f}/kWh peak window it occupied."
                    ),
                    proposed_action={
                        "kind": "defer_to_off_peak",
                        "job_id": job_id,
                        "zone": ev.get("zone"),
                        "gpu_ids": gpu_ids,
                        "peak_rate": peak_rate,
                        "off_peak_rate": float(off_rate),
                        "rate_delta": round(delta, 6),
                        "shifted_kwh": ev.get("peak_kwh"),
                        "off_peak_window_hours": ev.get("off_peak_window_hours"),
                    },
                    rationale=(
                        "The job is short, carries no deadline constraint, and sits at or below "
                        "the deferrable priority ceiling, so the same kilowatt-hours were "
                        "purchasable at the off-peak rate."
                    ),
                    source=f"detector:tariff:off_peak_rank_{rank}",
                    claim=self._claim(
                        self._segment_intervals(dataset, gpu_ids, segments),
                        basis=(
                            f"{float(ev.get('peak_kwh') or 0.0):.2f} kWh consumed inside peak "
                            f"tariff windows; the quantity is unchanged and only the rate moves."
                        ),
                    ),
                    rate_override=delta,
                    rate_explanation=(
                        f"Priced at the tariff delta of ${delta:.4f}/kWh (peak "
                        f"${peak_rate:.4f} minus off-peak ${float(off_rate):.4f}); shifting a job "
                        "moves the same kilowatt-hours to a cheaper hour, it does not remove them."
                    ),
                )
            )

        if len(segments) > 1:
            largest = max(segments, key=lambda s: float(s.get("kwh") or 0.0))
            delta = peak_rate - float(rates[0])
            if delta > 0:
                candidates.append(
                    ResourceCandidate(
                        kind="defer_partial",
                        description=(
                            f"Shift only the {float(largest['kwh']):.1f} kWh {job_id} drew in its "
                            "most expensive peak segment."
                        ),
                        proposed_action={
                            "kind": "defer_to_off_peak",
                            "job_id": job_id,
                            "zone": ev.get("zone"),
                            "gpu_ids": gpu_ids,
                            "partial": True,
                            "rate_delta": round(delta, 6),
                            "shifted_kwh": largest.get("kwh"),
                            "off_peak_window_hours": ev.get("off_peak_window_hours"),
                        },
                        rationale=(
                            "A smaller shift that only has to clear one tariff boundary, for the "
                            "case where the full run cannot be moved."
                        ),
                        source="detector:tariff:partial_shift",
                        claim=self._claim(
                            self._segment_intervals(dataset, gpu_ids, [largest]),
                            basis="kWh drawn inside the single most expensive peak segment.",
                        ),
                        rate_override=delta,
                        rate_explanation=(
                            f"Priced at the tariff delta of ${delta:.4f}/kWh, applied to one "
                            "peak segment only."
                        ),
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
        checked = ["claimed_resources_exist", "power_telemetry_covers_claimed_window"]
        violations: list[str] = []

        gpus = dataset.gpu_by_id()
        claimed_gpu_ids = sorted({i.resource_id for i in candidate.claim.resource_intervals})
        missing = [g for g in claimed_gpu_ids if g not in gpus]
        if missing:
            violations.append(f"Claimed GPUs are not in the cluster inventory: {missing[:3]}")
        if not candidate.claim.resource_intervals:
            violations.append("Candidate claims no metered energy interval")

        coverage = self._claim_coverage(dataset, candidate)
        if coverage < MIN_TELEMETRY_COVERAGE:
            violations.append(
                f"Telemetry covers only {coverage:.0%} of the claimed window; the energy claim "
                "is not provable from data"
            )

        if observation.signal_type is OpportunityType.CAPPED_CLOCKS:
            checked += ["cap_window_overlaps_active_work", "throttle_fraction_material"]
            if float(ev.get("active_fraction") or 0.0) <= 0.0:
                violations.append(
                    "Clock cap window contains no active work; a throttled idle GPU stretches "
                    "nothing and wastes no extra energy"
                )
            if float(ev.get("throttle_fraction") or 0.0) < MIN_THROTTLE_FRACTION:
                violations.append("Throttle is below the material threshold for this domain")
            if action.get("kind") == "relocate_to_unthrottled_peer":
                checked.append("peer_gpu_still_uncapped")
                peer = str(action.get("peer_gpu_id") or "")
                start, end = self._evidence_window(ev)
                if peer not in gpus:
                    violations.append(f"Peer GPU {peer} is not in the cluster inventory")
                elif start and end and self._capped_in(dataset, peer, start, end):
                    violations.append(f"Peer GPU {peer} was itself capped during the window")

        elif observation.signal_type is OpportunityType.PUE_PLACEMENT:
            checked += [
                "target_facility_exists",
                "target_facility_lower_pue",
                "target_facility_has_capacity",
            ]
            violations += self._validate_relocation(dataset, observation, action)

        elif observation.signal_type is OpportunityType.OFF_PEAK_SHIFT:
            checked += ["job_is_deferrable", "off_peak_window_fits_runtime", "tariff_delta_positive"]
            job = dataset.job_by_id().get(str(action.get("job_id") or ""))
            if job is None:
                violations.append("Job behind the shift is no longer in the dataset")
            else:
                reason = self._deferrable_reason(job)
                if reason:
                    violations.append(f"Job {job.job_id} is not deferrable: {reason}")
            window_hours = float(action.get("off_peak_window_hours") or 0.0)
            run_hours = float(ev.get("run_hours") or 0.0)
            if window_hours + 1e-9 < run_hours:
                violations.append(
                    f"Longest off-peak window is {window_hours:.1f}h against a {run_hours:.1f}h "
                    "run; the job does not fit inside it"
                )
            if float(action.get("rate_delta") or 0.0) <= 0.0:
                violations.append("Off-peak rate is not cheaper than the peak rate that was paid")

        return checked, violations

    def _validate_relocation(
        self, dataset: ClusterDataset, observation: ResourceObservation, action: dict
    ) -> list[str]:
        """A move is only a saving if the cheaper building could have taken it."""
        violations: list[str] = []
        zone = str(action.get("to_zone") or "")
        target = next((f for f in dataset.facilities if f.zone == zone), None)
        if target is None:
            return [f"Target facility {zone or '(unnamed)'} has no profile in the dataset"]
        source_pue = float(observation.evidence.get("source_pue") or 0.0)
        if target.pue >= source_pue:
            violations.append(
                f"Facility {zone} has PUE {target.pue:.2f}, no better than the "
                f"{source_pue:.2f} already paid"
            )

        known_nodes = dataset.node_by_id()
        present = [n for n in target.node_ids if n in known_nodes]
        if not present:
            return violations + [
                f"Facility {zone} lists no nodes present in the cluster inventory; the move has "
                "nowhere to land"
            ]

        gpu_ids = list(action.get("gpu_ids") or [])
        needed = len(gpu_ids)
        gpu_type = self._gpu_type_name(dataset, gpu_ids[0]) if gpu_ids else None
        start, end = self._evidence_window(observation.evidence)
        free = self._free_gpu_ids(dataset, present, start, end, gpu_type)
        if len(free) < needed:
            violations.append(
                f"Facility {zone} had {len(free)} free {gpu_type or 'matching'} GPU(s) against "
                f"{needed} needed; relocating is rearrangement that recovers nothing"
            )
        return violations

    # ------------------------------------------------------------------- claim

    def claim_cap(self, dataset: ClusterDataset, observation: ResourceObservation) -> float:
        """No claim may exceed what this hardware could physically have drawn.

        Everything in this domain is an energy difference, and an energy
        difference above the total energy available is not a conservative
        estimate, it is a nonsense number. TDP x GPU count x hours x PUE is
        that ceiling.
        """
        ev = observation.evidence
        gpu_ids = list(ev.get("cap_gpu_ids") or observation.affected_gpu_ids)
        hours = float(ev.get("cap_hours") or 0.0)
        pue = max(1.0, float(ev.get("cap_pue") or 1.0))
        if hours <= 0 or not gpu_ids:
            return 0.0
        watts = sum(self._tdp_watts(dataset, gpu_id) for gpu_id in gpu_ids)
        return watts * hours * pue / 1000.0

    # ------------------------------------------------------------ presentation

    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        kwh = candidate.claim.quantity(Meter.KWH)
        hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        kwh_month = (kwh / hours) * per_month if hours > 0 else 0.0
        rate = (
            candidate.rate_override
            if candidate.rate_override is not None
            else self.pricing.rate_for(Meter.KWH)
        )
        dollars = kwh_month * rate
        action = candidate.proposed_action or {}
        ev = observation.evidence
        money = f"{kwh_month:,.0f} kWh/month (${dollars:,.0f}/month)"

        if observation.signal_type is OpportunityType.CAPPED_CLOCKS:
            head = (
                f"Investigate the {float(ev.get('throttle_fraction') or 0):.0%} clock cap on GPU "
                f"{observation.resource_id} (node {self._node_of(dataset, observation.resource_id)}"
                f", cause: {action.get('cap_reason') or 'unrecorded'}) and clear it at source — "
                f"cooling, airflow, or the site power budget — worth {money}"
            )
            if action.get("kind") == "relocate_to_unthrottled_peer":
                head = (
                    f"Move this work off throttled GPU {observation.resource_id} onto the uncapped "
                    f"{action.get('peer_gpu_id')} of the same type, worth {money}"
                )
        elif observation.signal_type is OpportunityType.PUE_PLACEMENT:
            head = (
                f"Schedule node {observation.resource_id}'s "
                f"{action.get('gpu_count', len(observation.affected_gpu_ids))} GPU(s) of work in "
                f"{action.get('to_zone')} (PUE {float(ev.get('target_pue') or 0):.2f}) rather than "
                f"{action.get('from_zone')} (PUE {float(ev.get('source_pue') or 0):.2f}), worth {money}"
            )
        else:
            head = (
                f"Submit job {observation.resource_id} into the "
                f"${float(action.get('off_peak_rate') or 0):.4f}/kWh off-peak window in zone "
                f"{action.get('zone') or 'default'} instead of the "
                f"${float(action.get('peak_rate') or 0):.4f}/kWh peak hours it ran in — same "
                f"energy, cheaper hour — worth {money}"
            )
        return (
            f"{head}. Confirm with the facilities and scheduling owners first. Requires human "
            "approval; Natilah changes nothing."
        )

    # ----------------------------------------------------------------- helpers

    def _prime(self, dataset: ClusterDataset) -> None:
        if self._cached_for is dataset:
            return
        samples: dict[str, list[GPUUtilizationSample]] = {}
        for sample in dataset.samples:
            samples.setdefault(sample.gpu_id, []).append(sample)
        for values in samples.values():
            values.sort(key=lambda s: s.timestamp)
        self._samples = samples
        self._facility_by_node = {
            node_id: facility
            for facility in dataset.facilities
            for node_id in facility.node_ids
        }
        self._cached_for = dataset

    def _window(self, dataset: ClusterDataset) -> tuple[datetime, datetime] | None:
        """Job window if there is one, otherwise whatever the power data spans."""
        window = dataset.window()
        if window is not None:
            return window
        stamps = [s.timestamp for s in dataset.samples]
        stamps += [c.start for c in dataset.clock_caps] + [c.end for c in dataset.clock_caps]
        if not stamps:
            return None
        return min(stamps), max(stamps)

    def _pue_for_gpu(self, dataset: ClusterDataset, gpu_id: str) -> float:
        gpu = dataset.gpu_by_id().get(gpu_id)
        if gpu is None:
            return 1.0
        facility = self._facility_by_node.get(gpu.node_id)
        return facility.pue if facility else 1.0

    def _zone_for_gpu(self, dataset: ClusterDataset, gpu_id: str) -> str:
        gpu = dataset.gpu_by_id().get(gpu_id)
        if gpu is None:
            return ""
        facility = self._facility_by_node.get(gpu.node_id)
        return facility.zone if facility else ""

    def _tdp_watts(self, dataset: ClusterDataset, gpu_id: str) -> float:
        gpu = dataset.gpu_by_id().get(gpu_id)
        if gpu is not None:
            return gpu.gpu_type.tdp_watts
        return resolve_gpu_type(gpu_id).tdp_watts

    def _gpu_type_name(self, dataset: ClusterDataset, gpu_id: str) -> str | None:
        gpu = dataset.gpu_by_id().get(gpu_id)
        return gpu.gpu_type.name if gpu else None

    def _node_of(self, dataset: ClusterDataset, gpu_id: str) -> str:
        gpu = dataset.gpu_by_id().get(gpu_id)
        return gpu.node_id if gpu else "unknown node"

    def _job_ids_on(
        self, dataset: ClusterDataset, gpu_ids: list[str], start: datetime, end: datetime
    ) -> list[str]:
        wanted = set(gpu_ids)
        return sorted(
            {
                s.job_id
                for s in dataset.samples
                if s.job_id and s.gpu_id in wanted and start <= s.timestamp <= end
            }
        )

    def _gpu_ids_for_job(self, dataset: ClusterDataset, job: Job) -> list[str]:
        allocation = dataset.allocation_by_job().get(job.job_id)
        if allocation and allocation.gpu_ids:
            return sorted(allocation.gpu_ids)
        return sorted({s.gpu_id for s in dataset.samples_for_job(job.job_id)})

    def _deferrable_reason(self, job: Job) -> str | None:
        """None when the job could have waited. A string is why it could not."""
        if job.start_time is None or job.end_time is None:
            return "run window is unknown"
        hours = _hours(job.start_time, job.end_time)
        if hours <= 0:
            return "run window is empty"
        if hours > MAX_DEFERRABLE_HOURS:
            return f"ran {hours:.1f}h, beyond the {MAX_DEFERRABLE_HOURS:.0f}h deferrable ceiling"
        if job.priority > DEFERRABLE_PRIORITY_MAX:
            return f"priority {job.priority} is above the deferrable ceiling"
        constraints = {str(k).lower(): str(v).lower() for k, v in (job.constraints or {}).items()}
        for key in DEADLINE_KEYS:
            if key in constraints:
                return f"carries a {key} constraint"
        if constraints.get("deferrable") in FALSEY:
            return "is explicitly marked non-deferrable"
        if constraints.get("interactive") in TRUTHY:
            return "is an interactive session"
        return None

    def _tariffs_for_zone(self, dataset: ClusterDataset, zone: str) -> list[PowerTariff]:
        scoped = [t for t in dataset.tariffs if t.zone == zone]
        return scoped or [t for t in dataset.tariffs if not t.zone]

    def _peak_segments(
        self, tariffs: list[PowerTariff], start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime, PowerTariff]]:
        """Where a run window intersects the peak hours of a daily tariff sheet."""
        peaks = [t for t in tariffs if t.is_peak]
        if not peaks:
            return []
        segments: list[tuple[datetime, datetime, PowerTariff]] = []
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        days = int((end - midnight).total_seconds() // 86400) + 1
        for offset in range(max(1, min(days, 14))):
            day = midnight + timedelta(days=offset)
            for tariff in peaks:
                lo = max(day + timedelta(hours=tariff.start_hour), start)
                hi = min(day + timedelta(hours=tariff.end_hour), end)
                if hi > lo:
                    segments.append((lo, hi, tariff))
        return sorted(segments, key=lambda s: s[0])

    def _longest_off_peak_hours(self, tariffs: list[PowerTariff]) -> float:
        """Longest contiguous cheap stretch, midnight wrap included."""
        spans = sorted((t.start_hour, t.end_hour) for t in tariffs if not t.is_peak)
        if not spans:
            return 0.0
        merged: list[list[int]] = [list(spans[0])]
        for lo, hi in spans[1:]:
            if lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        longest = max(hi - lo for lo, hi in merged)
        if len(merged) > 1 and merged[0][0] == 0 and merged[-1][1] == 24:
            longest = max(longest, (24 - merged[-1][0]) + merged[0][1])
        return float(longest)

    def _unthrottled_peer(
        self, dataset: ClusterDataset, gpu_id: str, start: datetime, end: datetime
    ) -> str | None:
        gpu = dataset.gpu_by_id().get(gpu_id)
        if gpu is None:
            return None
        busy = {
            a_gpu
            for a in dataset.allocations
            if a.start_time < end and (a.end_time or end) > start
            for a_gpu in a.gpu_ids
        }
        for peer in dataset.gpus:
            if peer.gpu_id == gpu_id or peer.gpu_type.name != gpu.gpu_type.name:
                continue
            if peer.gpu_id in busy or self._capped_in(dataset, peer.gpu_id, start, end):
                continue
            return peer.gpu_id
        return None

    def _capped_in(
        self, dataset: ClusterDataset, gpu_id: str, start: datetime, end: datetime
    ) -> bool:
        return any(
            c.gpu_id == gpu_id
            and c.throttle_fraction >= MIN_THROTTLE_FRACTION
            and c.start < end
            and c.end > start
            for c in dataset.clock_caps
        )

    def _free_gpu_ids(
        self,
        dataset: ClusterDataset,
        node_ids: list[str],
        start: datetime | None,
        end: datetime | None,
        gpu_type: str | None,
    ) -> list[str]:
        allocated: set[str] = set()
        if start is not None and end is not None:
            for allocation in dataset.allocations:
                if allocation.start_time < end and (allocation.end_time or end) > start:
                    allocated.update(allocation.gpu_ids)
        wanted = set(node_ids)
        return [
            g.gpu_id
            for g in dataset.gpus
            if g.node_id in wanted
            and g.gpu_id not in allocated
            and gpu_type_matches(gpu_type, g.gpu_type.name)
        ]

    def _claim_coverage(self, dataset: ClusterDataset, candidate: ResourceCandidate) -> float:
        intervals = candidate.claim.resource_intervals
        if not intervals:
            return 0.0
        coverages = [
            self.energy(dataset, i.resource_id, i.start, i.end).coverage for i in intervals
        ]
        return min(coverages)

    def _evidence_window(self, evidence: dict) -> tuple[datetime | None, datetime | None]:
        return _parse_dt(evidence.get("window_start")), _parse_dt(evidence.get("window_end"))

    def _energy_evidence(self, energies: list[EnergyWindow], **extra) -> dict:
        measured = any(e.measured for e in energies)
        return {
            "measured_power": measured,
            "energy_source": "measured power_watts" if measured else "TDP x utilization fallback",
            "telemetry_coverage": round(min((e.coverage for e in energies), default=0.0), 4),
            "active_fraction": round(max((e.active_fraction for e in energies), default=0.0), 4),
            "mean_watts": round(sum(e.mean_watts for e in energies), 2),
            "it_kwh_measured": round(sum(e.kwh_it for e in energies), 6),
            "facility_kwh": round(sum(e.kwh_facility for e in energies), 6),
            "assumptions": self._assumptions(measured),
            **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in extra.items()},
        }

    def _assumptions(self, measured: bool) -> list[str]:
        assumptions = [
            "Facility energy is IT energy grossed up by the covering FacilityProfile's PUE; "
            "nodes with no facility profile are metered at PUE 1.0 (IT draw only).",
            f"Throttle overhead counts only the static share of draw (assumed "
            f"{STATIC_POWER_FRACTION:.0%}) over the added runtime; dynamic energy per unit of "
            "work is assumed unchanged by clock speed and is not claimed.",
            "Clock-limited throughput is assumed proportional to clock, so a card at fraction f "
            "of its rated clock holds the same work 1/f as long.",
        ]
        if measured:
            assumptions.append(
                "Energy integrated trapezoidally from measured power_watts samples."
            )
        else:
            assumptions.append(
                "No power_watts telemetry: energy inferred from rated TDP x utilization, which "
                "ignores the idle floor and therefore understates real draw. Confidence is "
                "reduced accordingly."
            )
        return assumptions

    # ------------------------------------------------------------ claim shapes

    def _interval(
        self, resource_id: str, start: datetime, end: datetime, kwh: float
    ) -> ResourceInterval | None:
        """kWh expressed as average kW held over a window, so kW x h = kWh."""
        hours = _hours(start, end)
        if hours <= 0 or kwh <= 0:
            return None
        return ResourceInterval(
            meter=Meter.KWH,
            resource_id=resource_id,
            start=start,
            end=end,
            magnitude=kwh / hours,
        )

    def _claim(self, intervals: list[ResourceInterval | None], basis: str) -> ResourceClaim:
        return ResourceClaim(
            resource_intervals=[i for i in intervals if i is not None],
            basis=basis,
            primary_meter=Meter.KWH,
        )

    def _per_gpu_intervals(
        self,
        dataset: ClusterDataset,
        gpu_ids: list[str],
        start: datetime,
        end: datetime,
        pue_delta: float,
    ) -> list[ResourceInterval | None]:
        return [
            self._interval(
                gpu_id, start, end, self.energy(dataset, gpu_id, start, end).kwh_it * pue_delta
            )
            for gpu_id in gpu_ids
        ]

    def _segment_intervals(
        self, dataset: ClusterDataset, gpu_ids: list[str], segments: list[dict]
    ) -> list[ResourceInterval | None]:
        intervals: list[ResourceInterval | None] = []
        for segment in segments:
            start = _parse_dt(segment.get("start"))
            end = _parse_dt(segment.get("end"))
            if start is None or end is None:
                continue
            for gpu_id in gpu_ids:
                energy = self.energy(dataset, gpu_id, start, end)
                intervals.append(self._interval(gpu_id, start, end, energy.kwh_facility))
        return intervals
