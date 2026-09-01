"""Inference efficiency agent.

Objective: the replica-hour meter.

Serving endpoints hold GPUs whether or not requests arrive. Three conditions
burn replica-hours for nothing:

    idle endpoint       zero or near-zero traffic against live replicas —
                        the model is deployed but nobody is calling it
    over-provisioned    traffic exists but GPU utilization is low enough
                        that fewer replicas would serve the same load
    batch headroom      requests arrive one at a time against a model that
                        supports batching, so each replica does less work
                        per forward pass than it could

Every claim is in replica-hours so it cannot collide with a GPU-hours claim
from a scheduling agent. The pricing defaults to the GPU rate of the card
type behind the endpoint.
"""

from __future__ import annotations

import math
from datetime import datetime

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
from natilah.models.resources import InferenceEndpoint, InferenceMetricSample

IDLE_RPS_THRESHOLD = 0.01
LOW_UTIL_PCT = 30.0
TARGET_UTIL_PCT = 70.0
LOW_BATCH_RATIO = 0.3
MIN_SAMPLES = 2
MIN_REPLICA_HOURS = 0.01


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class InferenceEfficiencyAgent(ResourceAgent):
    name = "inference_efficiency_agent"
    objective = AgentObjective.INFERENCE_EFFICIENCY
    primary_meter = Meter.REPLICA_HOURS
    signal_types = (
        OpportunityType.IDLE_ENDPOINT,
        OpportunityType.OVER_PROVISIONED_REPLICAS,
        OpportunityType.BATCH_HEADROOM,
    )
    finding_title = "Inference serving waste"

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        window = dataset.window()
        return [
            *self._detect_idle(dataset, window),
            *self._detect_over_provisioned(dataset, window),
            *self._detect_batch_headroom(dataset, window),
        ]

    def _window_for_endpoint(
        self,
        dataset: ClusterDataset,
        endpoint: InferenceEndpoint,
        global_window: tuple[datetime, datetime] | None,
    ) -> tuple[datetime, datetime] | None:
        samples = dataset.samples_for_endpoint(endpoint.endpoint_id)
        if len(samples) >= MIN_SAMPLES:
            return samples[0].timestamp, samples[-1].timestamp
        return global_window

    def _detect_idle(
        self,
        dataset: ClusterDataset,
        window: tuple[datetime, datetime] | None,
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for ep in dataset.endpoints:
            w = self._window_for_endpoint(dataset, ep, window)
            if w is None:
                continue
            samples = dataset.samples_for_endpoint(ep.endpoint_id)
            if len(samples) < MIN_SAMPLES:
                continue
            avg_rps = _mean([s.requests_per_second for s in samples])
            if avg_rps >= IDLE_RPS_THRESHOLD:
                continue
            total_gpus = ep.replicas * ep.gpus_per_replica
            hours = _hours(w[0], w[1])
            wasted = total_gpus * hours
            if wasted < MIN_REPLICA_HOURS:
                continue
            observations.append(
                ResourceObservation(
                    observation_id=f"idle_endpoint:{ep.endpoint_id}",
                    signal_type=OpportunityType.IDLE_ENDPOINT,
                    resource_id=ep.endpoint_id,
                    timestamp=w[0],
                    severity=round(min(1.0, 1.0 - avg_rps / max(IDLE_RPS_THRESHOLD, 1e-9)), 4),
                    description=(
                        f"Endpoint {ep.endpoint_id} ({ep.model or ep.name}) holds "
                        f"{ep.replicas} replica(s) x {ep.gpus_per_replica} GPU(s) = "
                        f"{total_gpus} {ep.gpu_type or 'GPU'}(s) with {avg_rps:.4f} RPS "
                        f"over {hours:.1f}h — effectively idle."
                    ),
                    affected_gpu_ids=list(ep.gpu_ids),
                    evidence={
                        "endpoint_id": ep.endpoint_id,
                        "model": ep.model,
                        "gpu_type": ep.gpu_type,
                        "replicas": ep.replicas,
                        "gpus_per_replica": ep.gpus_per_replica,
                        "total_gpus": total_gpus,
                        "avg_rps": round(avg_rps, 6),
                        "sample_count": len(samples),
                        "window_start": w[0].isoformat(),
                        "window_end": w[1].isoformat(),
                        "wasted_replica_hours": round(wasted, 4),
                        "signal_reason": (
                            f"{avg_rps:.4f} RPS across {len(samples)} samples — "
                            "no meaningful traffic"
                        ),
                    },
                    data_completeness=min(1.0, len(samples) / 10.0),
                    signal_strength=round(min(1.0, 1.0 - avg_rps / max(IDLE_RPS_THRESHOLD, 1e-9)), 4),
                )
            )
        return observations

    def _detect_over_provisioned(
        self,
        dataset: ClusterDataset,
        window: tuple[datetime, datetime] | None,
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for ep in dataset.endpoints:
            if ep.replicas <= ep.min_replicas:
                continue
            w = self._window_for_endpoint(dataset, ep, window)
            if w is None:
                continue
            samples = dataset.samples_for_endpoint(ep.endpoint_id)
            if len(samples) < MIN_SAMPLES:
                continue
            avg_util = _mean([s.gpu_utilization_pct for s in samples])
            if avg_util >= LOW_UTIL_PCT:
                continue
            avg_rps = _mean([s.requests_per_second for s in samples])
            if avg_rps < IDLE_RPS_THRESHOLD:
                continue
            needed = max(ep.min_replicas, math.ceil(ep.replicas * avg_util / TARGET_UTIL_PCT))
            excess = ep.replicas - needed
            if excess <= 0:
                continue
            hours = _hours(w[0], w[1])
            wasted = excess * ep.gpus_per_replica * hours
            if wasted < MIN_REPLICA_HOURS:
                continue
            observations.append(
                ResourceObservation(
                    observation_id=f"over_provisioned:{ep.endpoint_id}",
                    signal_type=OpportunityType.OVER_PROVISIONED_REPLICAS,
                    resource_id=ep.endpoint_id,
                    timestamp=w[0],
                    severity=round(min(1.0, excess / max(ep.replicas, 1)), 4),
                    description=(
                        f"Endpoint {ep.endpoint_id} runs {ep.replicas} replicas at "
                        f"{avg_util:.1f}% average GPU utilization; {needed} would serve "
                        f"the same {avg_rps:.1f} RPS load."
                    ),
                    affected_gpu_ids=list(ep.gpu_ids),
                    evidence={
                        "endpoint_id": ep.endpoint_id,
                        "model": ep.model,
                        "gpu_type": ep.gpu_type,
                        "replicas": ep.replicas,
                        "needed_replicas": needed,
                        "excess_replicas": excess,
                        "gpus_per_replica": ep.gpus_per_replica,
                        "avg_util_pct": round(avg_util, 2),
                        "avg_rps": round(avg_rps, 4),
                        "sample_count": len(samples),
                        "window_start": w[0].isoformat(),
                        "window_end": w[1].isoformat(),
                        "wasted_replica_hours": round(wasted, 4),
                        "signal_reason": (
                            f"{avg_util:.1f}% utilization across {ep.replicas} replicas — "
                            f"{excess} could be removed"
                        ),
                    },
                    data_completeness=min(1.0, len(samples) / 10.0),
                    signal_strength=round(min(1.0, (LOW_UTIL_PCT - avg_util) / LOW_UTIL_PCT), 4),
                )
            )
        return observations

    def _detect_batch_headroom(
        self,
        dataset: ClusterDataset,
        window: tuple[datetime, datetime] | None,
    ) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for ep in dataset.endpoints:
            if ep.max_batch_size <= 1 or ep.replicas <= 1:
                continue
            w = self._window_for_endpoint(dataset, ep, window)
            if w is None:
                continue
            samples = dataset.samples_for_endpoint(ep.endpoint_id)
            if len(samples) < MIN_SAMPLES:
                continue
            avg_batch = _mean([s.batch_size for s in samples])
            batch_ratio = avg_batch / ep.max_batch_size
            if batch_ratio >= LOW_BATCH_RATIO:
                continue
            avg_rps = _mean([s.requests_per_second for s in samples])
            if avg_rps < IDLE_RPS_THRESHOLD:
                continue
            hours = _hours(w[0], w[1])
            headroom_fraction = 1.0 - batch_ratio
            saveable_replicas = max(1, math.floor(ep.replicas * headroom_fraction * 0.5))
            saveable_replicas = min(saveable_replicas, ep.replicas - 1)
            wasted = saveable_replicas * ep.gpus_per_replica * hours
            if wasted < MIN_REPLICA_HOURS:
                continue
            observations.append(
                ResourceObservation(
                    observation_id=f"batch_headroom:{ep.endpoint_id}",
                    signal_type=OpportunityType.BATCH_HEADROOM,
                    resource_id=ep.endpoint_id,
                    timestamp=w[0],
                    severity=round(min(1.0, headroom_fraction), 4),
                    description=(
                        f"Endpoint {ep.endpoint_id} averages batch size {avg_batch:.1f} "
                        f"against a max of {ep.max_batch_size} ({batch_ratio:.0%} fill) "
                        f"across {ep.replicas} replicas — better batching could retire "
                        f"{saveable_replicas}."
                    ),
                    affected_gpu_ids=list(ep.gpu_ids),
                    evidence={
                        "endpoint_id": ep.endpoint_id,
                        "model": ep.model,
                        "gpu_type": ep.gpu_type,
                        "replicas": ep.replicas,
                        "max_batch_size": ep.max_batch_size,
                        "avg_batch_size": round(avg_batch, 2),
                        "batch_ratio": round(batch_ratio, 4),
                        "saveable_replicas": saveable_replicas,
                        "gpus_per_replica": ep.gpus_per_replica,
                        "avg_rps": round(avg_rps, 4),
                        "sample_count": len(samples),
                        "window_start": w[0].isoformat(),
                        "window_end": w[1].isoformat(),
                        "wasted_replica_hours": round(wasted, 4),
                        "signal_reason": (
                            f"{batch_ratio:.0%} batch fill across {ep.replicas} replicas — "
                            f"batching headroom could save {saveable_replicas} replica(s)"
                        ),
                    },
                    data_completeness=min(1.0, len(samples) / 10.0),
                    signal_strength=round(headroom_fraction, 4),
                )
            )
        return observations

    # -------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.IDLE_ENDPOINT:
            return self._idle_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.OVER_PROVISIONED_REPLICAS:
            return self._over_provisioned_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.BATCH_HEADROOM:
            return self._batch_candidates(dataset, observation)
        return []

    def _idle_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        ep = self._get_endpoint(dataset, str(ev.get("endpoint_id", "")))
        if ep is None:
            return []
        start, end = self._evidence_window(ev)
        if start is None or end is None:
            return []
        wasted = float(ev.get("wasted_replica_hours", 0))
        total_gpus = int(ev.get("total_gpus", ep.replicas * ep.gpus_per_replica))
        rate = self.gpu_rate(ep.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="shut_down_endpoint",
                description=(
                    f"Shut down endpoint {ep.endpoint_id} — it received no meaningful "
                    f"traffic over the observation window."
                ),
                proposed_action={
                    "kind": "shut_down_endpoint",
                    "endpoint_id": ep.endpoint_id,
                    "replicas": ep.replicas,
                    "recovered_replica_hours": round(wasted, 4),
                },
                rationale=(
                    "An endpoint with zero traffic is holding GPUs that could serve "
                    "other workloads or be released entirely."
                ),
                source="detector:idle:shutdown",
                claim=self._claim(ep.endpoint_id, start, end, total_gpus),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="scale_to_zero",
                description=(
                    f"Enable scale-to-zero on {ep.endpoint_id} so replicas spin down "
                    "when traffic is absent and spin up on first request."
                ),
                proposed_action={
                    "kind": "enable_scale_to_zero",
                    "endpoint_id": ep.endpoint_id,
                    "current_replicas": ep.replicas,
                    "target_min_replicas": 0,
                    "recovered_replica_hours": round(wasted, 4),
                },
                rationale=(
                    "Scale-to-zero preserves the deployment while releasing GPUs during "
                    "idle periods; cold-start latency is the trade-off."
                ),
                source="detector:idle:scale_to_zero",
                claim=self._claim(ep.endpoint_id, start, end, total_gpus),
                gpu_rate=rate,
            )
        )

        if not ep.autoscaling_enabled:
            candidates.append(
                ResourceCandidate(
                    kind="enable_autoscaling",
                    description=(
                        f"Enable autoscaling on {ep.endpoint_id} with min_replicas=0 so "
                        "the endpoint responds to demand rather than holding a fixed fleet."
                    ),
                    proposed_action={
                        "kind": "enable_autoscaling",
                        "endpoint_id": ep.endpoint_id,
                        "current_replicas": ep.replicas,
                        "suggested_min": 0,
                        "suggested_max": ep.replicas,
                    },
                    rationale=(
                        "Autoscaling with a zero floor lets the platform reclaim all "
                        "replicas in idle windows while preserving capacity for bursts."
                    ),
                    source="detector:idle:autoscaling",
                    claim=self._claim(ep.endpoint_id, start, end, total_gpus),
                    gpu_rate=rate,
                )
            )
        return candidates

    def _over_provisioned_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        ep = self._get_endpoint(dataset, str(ev.get("endpoint_id", "")))
        if ep is None:
            return []
        start, end = self._evidence_window(ev)
        if start is None or end is None:
            return []
        excess = int(ev.get("excess_replicas", 0))
        needed = int(ev.get("needed_replicas", ep.min_replicas))
        rate = self.gpu_rate(ep.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="reduce_replicas",
                description=(
                    f"Reduce {ep.endpoint_id} from {ep.replicas} to {needed} replicas — "
                    f"the observed {float(ev.get('avg_util_pct', 0)):.1f}% utilization "
                    "fits in fewer."
                ),
                proposed_action={
                    "kind": "reduce_replicas",
                    "endpoint_id": ep.endpoint_id,
                    "from_replicas": ep.replicas,
                    "to_replicas": needed,
                    "excess": excess,
                },
                rationale=(
                    "Fewer replicas serving the same traffic at higher utilization — "
                    "the excess GPUs are released."
                ),
                source="detector:over_provisioned:reduce",
                claim=self._claim(ep.endpoint_id, start, end, excess * ep.gpus_per_replica),
                gpu_rate=rate,
            )
        )

        if not ep.autoscaling_enabled:
            candidates.append(
                ResourceCandidate(
                    kind="enable_autoscaling",
                    description=(
                        f"Enable autoscaling on {ep.endpoint_id} with min={needed}, "
                        f"max={ep.replicas} so it scales down during low-traffic periods."
                    ),
                    proposed_action={
                        "kind": "enable_autoscaling",
                        "endpoint_id": ep.endpoint_id,
                        "suggested_min": needed,
                        "suggested_max": ep.replicas,
                    },
                    rationale=(
                        "Autoscaling adapts replica count to demand; the current "
                        "fixed count over-provisions during steady-state."
                    ),
                    source="detector:over_provisioned:autoscaling",
                    claim=self._claim(ep.endpoint_id, start, end, excess * ep.gpus_per_replica),
                    gpu_rate=rate,
                )
            )

        conservative = max(ep.min_replicas, needed + 1)
        conservative_excess = ep.replicas - conservative
        if conservative_excess > 0:
            candidates.append(
                ResourceCandidate(
                    kind="right_size_conservative",
                    description=(
                        f"Reduce to {conservative} replicas — one above the computed "
                        f"minimum of {needed}, leaving headroom for traffic spikes."
                    ),
                    proposed_action={
                        "kind": "reduce_replicas",
                        "endpoint_id": ep.endpoint_id,
                        "from_replicas": ep.replicas,
                        "to_replicas": conservative,
                        "excess": conservative_excess,
                    },
                    rationale=(
                        "A conservative right-size that keeps one spare replica for "
                        "burst absorption."
                    ),
                    source="detector:over_provisioned:conservative",
                    claim=self._claim(
                        ep.endpoint_id, start, end,
                        conservative_excess * ep.gpus_per_replica,
                    ),
                    gpu_rate=rate,
                )
            )
        return candidates

    def _batch_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        ep = self._get_endpoint(dataset, str(ev.get("endpoint_id", "")))
        if ep is None:
            return []
        start, end = self._evidence_window(ev)
        if start is None or end is None:
            return []
        saveable = int(ev.get("saveable_replicas", 0))
        rate = self.gpu_rate(ep.gpu_type)
        candidates: list[ResourceCandidate] = []

        candidates.append(
            ResourceCandidate(
                kind="increase_client_batch_size",
                description=(
                    f"Increase client-side batching for {ep.endpoint_id} — current "
                    f"average {float(ev.get('avg_batch_size', 0)):.1f} against a max of "
                    f"{ep.max_batch_size}, then reduce replica count by {saveable}."
                ),
                proposed_action={
                    "kind": "increase_batch_size",
                    "endpoint_id": ep.endpoint_id,
                    "current_avg_batch": ev.get("avg_batch_size"),
                    "max_batch_size": ep.max_batch_size,
                    "saveable_replicas": saveable,
                },
                rationale=(
                    "Higher batch fill means each forward pass does more useful work, "
                    "so fewer replicas serve the same throughput."
                ),
                source="detector:batch:client_batching",
                claim=self._claim(ep.endpoint_id, start, end, saveable * ep.gpus_per_replica),
                gpu_rate=rate,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="enable_server_batching",
                description=(
                    f"Enable or tune server-side dynamic batching on {ep.endpoint_id} "
                    f"to fill batches closer to {ep.max_batch_size}."
                ),
                proposed_action={
                    "kind": "enable_server_batching",
                    "endpoint_id": ep.endpoint_id,
                    "max_batch_size": ep.max_batch_size,
                    "saveable_replicas": saveable,
                },
                rationale=(
                    "Server-side batching accumulates requests into fuller batches "
                    "without requiring client changes, at the cost of slight latency."
                ),
                source="detector:batch:server_batching",
                claim=self._claim(ep.endpoint_id, start, end, saveable * ep.gpus_per_replica),
                gpu_rate=rate,
            )
        )

        if saveable >= 2:
            half = max(1, saveable // 2)
            candidates.append(
                ResourceCandidate(
                    kind="consolidate_replicas",
                    description=(
                        f"Consolidate {ep.endpoint_id} by {half} replicas — a conservative "
                        "step that captures part of the batching headroom without "
                        "requiring client changes."
                    ),
                    proposed_action={
                        "kind": "reduce_replicas",
                        "endpoint_id": ep.endpoint_id,
                        "from_replicas": ep.replicas,
                        "to_replicas": ep.replicas - half,
                        "excess": half,
                    },
                    rationale=(
                        "Retiring half the saveable replicas captures the floor of "
                        "the batching opportunity without touching the request path."
                    ),
                    source="detector:batch:consolidate",
                    claim=self._claim(
                        ep.endpoint_id, start, end, half * ep.gpus_per_replica
                    ),
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
        checked = ["endpoint_exists", "has_telemetry", "replicas_positive"]
        violations: list[str] = []

        ep = self._get_endpoint(dataset, str(ev.get("endpoint_id", "")))
        if ep is None:
            violations.append(
                f"Endpoint {ev.get('endpoint_id')} not found in the dataset"
            )
            return checked, violations

        samples = dataset.samples_for_endpoint(ep.endpoint_id)
        if len(samples) < MIN_SAMPLES:
            violations.append(
                f"Endpoint {ep.endpoint_id} has only {len(samples)} telemetry "
                f"sample(s); minimum is {MIN_SAMPLES}"
            )

        if ep.replicas <= 0:
            violations.append(f"Endpoint {ep.endpoint_id} reports 0 replicas")

        action = candidate.proposed_action or {}
        kind = action.get("kind")

        if kind in ("reduce_replicas", "shut_down_endpoint"):
            checked.append("target_replicas_valid")
            to_replicas = action.get("to_replicas", 0)
            if to_replicas is not None and int(to_replicas) < 0:
                violations.append("Target replica count is negative")

        if observation.signal_type is OpportunityType.OVER_PROVISIONED_REPLICAS:
            checked.append("has_traffic")
            avg_rps = float(ev.get("avg_rps", 0))
            if avg_rps < IDLE_RPS_THRESHOLD:
                violations.append(
                    "Endpoint appears idle — over-provisioning finding requires "
                    "actual traffic to be meaningful"
                )

        if observation.signal_type is OpportunityType.BATCH_HEADROOM:
            checked.append("batching_supported")
            if ep.max_batch_size <= 1:
                violations.append(
                    f"Endpoint {ep.endpoint_id} max_batch_size is {ep.max_batch_size}; "
                    "batching is not supported"
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
        replica_hours = float(ev.get("wasted_replica_hours", 0))
        analysis_hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        rh_month = (replica_hours / analysis_hours) * per_month if analysis_hours > 0 else 0.0
        rate = candidate.gpu_rate or self.gpu_rate(str(ev.get("gpu_type", "")))
        dollars = rh_month * rate
        money = f"{rh_month:,.0f} replica-h/month (${dollars:,.0f}/month)"
        action = candidate.proposed_action or {}

        if observation.signal_type is OpportunityType.IDLE_ENDPOINT:
            kind = action.get("kind", "")
            if kind == "shut_down_endpoint":
                head = (
                    f"Shut down endpoint {observation.resource_id} — no meaningful "
                    f"traffic in the observation window — worth {money}"
                )
            elif kind == "enable_scale_to_zero":
                head = (
                    f"Enable scale-to-zero on endpoint {observation.resource_id} so "
                    f"idle replicas release their GPUs — worth {money}"
                )
            else:
                head = (
                    f"Enable autoscaling with min_replicas=0 on endpoint "
                    f"{observation.resource_id} — worth {money}"
                )
        elif observation.signal_type is OpportunityType.OVER_PROVISIONED_REPLICAS:
            head = (
                f"Reduce endpoint {observation.resource_id} from "
                f"{ev.get('replicas')} to {action.get('to_replicas', ev.get('needed_replicas'))} "
                f"replicas — worth {money}"
            )
        else:
            head = (
                f"Improve batching on endpoint {observation.resource_id} (avg "
                f"{float(ev.get('avg_batch_size', 0)):.1f}/{ev.get('max_batch_size')} fill) "
                f"and consolidate {ev.get('saveable_replicas')} replica(s) — worth {money}"
            )

        return (
            f"{head}. Confirm with the serving team first. Requires human "
            "approval; Natilah changes nothing."
        )

    # ----------------------------------------------------------------- helpers

    def _get_endpoint(
        self, dataset: ClusterDataset, endpoint_id: str
    ) -> InferenceEndpoint | None:
        for ep in dataset.endpoints:
            if ep.endpoint_id == endpoint_id:
                return ep
        return None

    def _evidence_window(
        self, evidence: dict
    ) -> tuple[datetime | None, datetime | None]:
        def _parse(key: str) -> datetime | None:
            v = evidence.get(key)
            if not v:
                return None
            try:
                return datetime.fromisoformat(str(v))
            except ValueError:
                return None
        return _parse("window_start"), _parse("window_end")

    def _claim(
        self,
        endpoint_id: str,
        start: datetime,
        end: datetime,
        magnitude: float,
    ) -> ResourceClaim:
        hours = _hours(start, end)
        if hours <= 0 or magnitude <= 0:
            return ResourceClaim(
                resource_intervals=[],
                basis="No recoverable replica-hours in this window.",
                primary_meter=Meter.REPLICA_HOURS,
            )
        return ResourceClaim(
            resource_intervals=[
                ResourceInterval(
                    meter=Meter.REPLICA_HOURS,
                    resource_id=endpoint_id,
                    start=start,
                    end=end,
                    magnitude=magnitude,
                ),
            ],
            basis=(
                f"{magnitude:.1f} GPU(s) worth of replicas x {hours:.1f}h = "
                f"{magnitude * hours:.1f} replica-hours recoverable."
            ),
            primary_meter=Meter.REPLICA_HOURS,
        )

    def claim_cap(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> float:
        ev = observation.evidence
        start, end = self._evidence_window(ev)
        if start is None or end is None:
            return 0.0
        ep = self._get_endpoint(dataset, str(ev.get("endpoint_id", "")))
        if ep is None:
            return 0.0
        hours = _hours(start, end)
        return ep.replicas * ep.gpus_per_replica * hours
