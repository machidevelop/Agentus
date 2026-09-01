"""Network-efficiency agent.

Objective: the GB-transferred meter.

Three conditions, three ways bandwidth costs money for nothing:

    cross-AZ traffic    bytes that crossed an availability-zone boundary when
                        both endpoints could have been co-located
    data locality       a job pulled its input across a zone boundary because
                        it was scheduled in the wrong zone for the data it reads
    image pull churn    the same container image pulled onto the same node
                        repeatedly, cache-miss after cache-miss, because the
                        node evicted it or a pre-pull policy was never set
"""

from __future__ import annotations

import logging
from collections import defaultdict

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.domain import (
    ClusterDataset,
    ResourceClaim,
    ResourceQuantity,
)
from natilah.models.enums import AgentObjective, Meter, OpportunityType
from natilah.models.resources import ImagePull, NetworkFlow

logger = logging.getLogger(__name__)

MIN_BILLABLE_GB = 0.01
MIN_CHURN_PULLS = 2
MIN_IMAGE_GB = 0.001


class NetworkEfficiencyAgent(ResourceAgent):
    name = "network_efficiency_agent"
    objective = AgentObjective.NETWORK_EFFICIENCY
    primary_meter = Meter.GB_TRANSFERRED
    signal_types = (
        OpportunityType.CROSS_AZ_TRAFFIC,
        OpportunityType.DATA_LOCALITY,
        OpportunityType.IMAGE_PULL_CHURN,
    )
    finding_title = "Network waste"

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        return [
            *self._detect_cross_az(dataset),
            *self._detect_data_locality(dataset),
            *self._detect_image_pull_churn(dataset),
        ]

    def _detect_cross_az(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        billable = [f for f in dataset.flows if f.is_billable and f.gb_transferred >= MIN_BILLABLE_GB]
        grouped: dict[str, list[NetworkFlow]] = defaultdict(list)
        for flow in billable:
            key = flow.job_id or f"{flow.src_zone}->{flow.dst_zone}"
            grouped[key].append(flow)

        observations: list[ResourceObservation] = []
        for key, flows in grouped.items():
            total_gb = sum(f.gb_transferred for f in flows)
            if total_gb < MIN_BILLABLE_GB:
                continue
            first = flows[0]
            dominant_kind = max(set(f.kind for f in flows), key=lambda k: sum(
                f.gb_transferred for f in flows if f.kind == k
            ))
            rate = self.pricing.rate_for(Meter.GB_TRANSFERRED, kind=dominant_kind)
            job_ids = sorted({f.job_id for f in flows if f.job_id})
            observations.append(
                ResourceObservation(
                    observation_id=f"cross_az:{key}",
                    signal_type=OpportunityType.CROSS_AZ_TRAFFIC,
                    resource_id=key,
                    timestamp=first.start,
                    severity=round(min(1.0, total_gb / 100.0), 4),
                    description=(
                        f"{total_gb:.1f} GB of {dominant_kind} traffic across "
                        f"{first.src_zone} -> {first.dst_zone} in {len(flows)} flow(s), "
                        f"costing ~${total_gb * rate:,.2f} at ${rate:.4f}/GB."
                    ),
                    affected_job_ids=job_ids,
                    evidence={
                        "total_gb": round(total_gb, 6),
                        "flow_count": len(flows),
                        "dominant_kind": dominant_kind,
                        "src_zone": first.src_zone,
                        "dst_zone": first.dst_zone,
                        "rate": rate,
                        "signal_reason": (
                            f"{total_gb:.1f} GB of billable cross-zone traffic"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, total_gb / 50.0), 4),
                    recurrence=max(0, len(flows) - 1),
                )
            )
        return observations

    def _detect_data_locality(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        cross_zone = [
            f for f in dataset.flows
            if f.src_zone and f.dst_zone and f.src_zone != f.dst_zone
            and f.job_id and f.gb_transferred >= MIN_BILLABLE_GB
        ]
        by_job: dict[str, list[NetworkFlow]] = defaultdict(list)
        for flow in cross_zone:
            by_job[flow.job_id].append(flow)

        node_zones = self._node_zones(dataset)
        for job_id, flows in by_job.items():
            total_gb = sum(f.gb_transferred for f in flows)
            if total_gb < MIN_BILLABLE_GB:
                continue
            src_zones = {f.src_zone for f in flows}
            for src_zone in src_zones:
                nodes_in_src = [
                    nid for nid, zone in node_zones.items() if zone == src_zone
                ]
                if not nodes_in_src:
                    continue
                zone_gb = sum(f.gb_transferred for f in flows if f.src_zone == src_zone)
                first = next(f for f in flows if f.src_zone == src_zone)
                observations.append(
                    ResourceObservation(
                        observation_id=f"data_locality:{job_id}:{src_zone}",
                        signal_type=OpportunityType.DATA_LOCALITY,
                        resource_id=job_id,
                        timestamp=first.start,
                        severity=round(min(1.0, zone_gb / 50.0), 4),
                        description=(
                            f"Job {job_id} pulled {zone_gb:.1f} GB from {src_zone} across zone "
                            f"boundaries; {len(nodes_in_src)} node(s) in {src_zone} could have "
                            "hosted the job without the transfer."
                        ),
                        affected_job_ids=[job_id],
                        evidence={
                            "total_gb": round(zone_gb, 6),
                            "src_zone": src_zone,
                            "dst_zone": first.dst_zone,
                            "nodes_in_src_zone": nodes_in_src[:10],
                            "flow_count": sum(1 for f in flows if f.src_zone == src_zone),
                            "signal_reason": (
                                f"{zone_gb:.1f} GB read from {src_zone} that could "
                                "have been local"
                            ),
                        },
                        data_completeness=1.0,
                        signal_strength=round(min(1.0, zone_gb / 30.0), 4),
                        recurrence=max(0, len(by_job) - 1),
                    )
                )
        return observations

    def _detect_image_pull_churn(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        misses = [p for p in dataset.image_pulls if not p.cache_hit and p.gb >= MIN_IMAGE_GB]
        grouped: dict[tuple[str, str], list[ImagePull]] = defaultdict(list)
        for pull in misses:
            grouped[(pull.node_id, pull.image)].append(pull)

        observations: list[ResourceObservation] = []
        for (node_id, image), pulls in grouped.items():
            if len(pulls) < MIN_CHURN_PULLS:
                continue
            total_gb = sum(p.gb for p in pulls)
            first = min(pulls, key=lambda p: p.timestamp)
            job_ids = sorted({p.job_id for p in pulls if p.job_id})
            observations.append(
                ResourceObservation(
                    observation_id=f"image_churn:{node_id}:{image}",
                    signal_type=OpportunityType.IMAGE_PULL_CHURN,
                    resource_id=f"{node_id}:{image}",
                    timestamp=first.timestamp,
                    severity=round(min(1.0, len(pulls) / 10.0), 4),
                    description=(
                        f"Image {image} pulled {len(pulls)} times onto node {node_id} "
                        f"without a cache hit, transferring {total_gb:.2f} GB total."
                    ),
                    affected_job_ids=job_ids,
                    evidence={
                        "node_id": node_id,
                        "image": image,
                        "pull_count": len(pulls),
                        "total_gb": round(total_gb, 6),
                        "first_pull": first.timestamp.isoformat(),
                        "last_pull": max(p.timestamp for p in pulls).isoformat(),
                        "signal_reason": (
                            f"{len(pulls)} cache misses for the same image on the same node"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, len(pulls) / 5.0), 4),
                    recurrence=max(0, len(pulls) - 2),
                )
            )
        return observations

    # ------------------------------------------------------------ candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.CROSS_AZ_TRAFFIC:
            return self._cross_az_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.DATA_LOCALITY:
            return self._data_locality_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.IMAGE_PULL_CHURN:
            return self._image_churn_candidates(dataset, observation)
        return []

    def _cross_az_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        total_gb = float(ev.get("total_gb") or 0.0)
        kind = str(ev.get("dominant_kind") or "cross_az")
        src_zone = str(ev.get("src_zone") or "")
        dst_zone = str(ev.get("dst_zone") or "")
        if total_gb <= 0:
            return []

        candidates: list[ResourceCandidate] = []
        candidates.append(
            ResourceCandidate(
                kind="colocate_endpoints",
                description=(
                    f"Move the communicating endpoints into the same zone to eliminate "
                    f"{total_gb:.1f} GB of {kind} traffic between {src_zone} and {dst_zone}."
                ),
                proposed_action={
                    "kind": "colocate_endpoints",
                    "src_zone": src_zone,
                    "dst_zone": dst_zone,
                    "eliminated_gb": round(total_gb, 6),
                },
                rationale=(
                    "Co-locating both sides of the transfer in one zone makes the "
                    "cross-zone charge disappear entirely."
                ),
                source="detector:cross_az:colocate",
                claim=self._quantity_claim(
                    observation.resource_id, total_gb,
                    f"{total_gb:.1f} GB of {kind} traffic between {src_zone} and {dst_zone}.",
                ),
                traffic_kind=kind,
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="replicate_data_locally",
                description=(
                    f"Replicate the source data into {dst_zone} so reads stay in-zone; "
                    f"eliminates {total_gb:.1f} GB of recurring cross-zone reads."
                ),
                proposed_action={
                    "kind": "replicate_data",
                    "src_zone": src_zone,
                    "dst_zone": dst_zone,
                    "eliminated_gb": round(total_gb * 0.8, 6),
                },
                rationale=(
                    "A local replica removes recurring reads at the cost of one-time "
                    "replication and storage; 80% reduction is conservative, accounting "
                    "for ongoing writes that still cross."
                ),
                source="detector:cross_az:replicate",
                claim=self._quantity_claim(
                    observation.resource_id, total_gb * 0.8,
                    f"80% of {total_gb:.1f} GB cross-zone reads, net of ongoing writes.",
                ),
                traffic_kind=kind,
            )
        )
        return candidates

    def _data_locality_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        total_gb = float(ev.get("total_gb") or 0.0)
        src_zone = str(ev.get("src_zone") or "")
        dst_zone = str(ev.get("dst_zone") or "")
        job_id = observation.resource_id
        if total_gb <= 0:
            return []

        candidates: list[ResourceCandidate] = []
        candidates.append(
            ResourceCandidate(
                kind="schedule_in_data_zone",
                description=(
                    f"Schedule job {job_id} in {src_zone} where its data lives, "
                    f"eliminating {total_gb:.1f} GB of cross-zone reads."
                ),
                proposed_action={
                    "kind": "schedule_in_data_zone",
                    "job_id": job_id,
                    "target_zone": src_zone,
                    "eliminated_gb": round(total_gb, 6),
                },
                rationale=(
                    "The job's input data is in a different zone from where the job ran; "
                    "scheduling it next to the data avoids the transfer entirely."
                ),
                source="detector:locality:schedule_in_data_zone",
                claim=self._quantity_claim(
                    job_id, total_gb,
                    f"{total_gb:.1f} GB read cross-zone by {job_id}; would be local if "
                    f"scheduled in {src_zone}.",
                ),
                traffic_kind="cross_az",
            )
        )

        candidates.append(
            ResourceCandidate(
                kind="replicate_data_to_job_zone",
                description=(
                    f"Replicate the data into {dst_zone} so {job_id} reads locally; "
                    f"eliminates future cross-zone reads."
                ),
                proposed_action={
                    "kind": "replicate_data",
                    "job_id": job_id,
                    "src_zone": src_zone,
                    "dst_zone": dst_zone,
                    "eliminated_gb": round(total_gb * 0.9, 6),
                },
                rationale=(
                    "A replica in the job's zone removes the read penalty at the cost "
                    "of one-time replication; 90% reduction allows for metadata reads "
                    "that still cross."
                ),
                source="detector:locality:replicate",
                claim=self._quantity_claim(
                    job_id, total_gb * 0.9,
                    f"90% of {total_gb:.1f} GB cross-zone reads for {job_id}.",
                ),
                traffic_kind="cross_az",
            )
        )
        return candidates

    def _image_churn_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        total_gb = float(ev.get("total_gb") or 0.0)
        pull_count = int(ev.get("pull_count") or 0)
        node_id = str(ev.get("node_id") or "")
        image = str(ev.get("image") or "")
        if total_gb <= 0 or pull_count < MIN_CHURN_PULLS:
            return []

        per_pull = total_gb / pull_count
        saved_pulls = pull_count - 1

        candidates: list[ResourceCandidate] = []
        candidates.append(
            ResourceCandidate(
                kind="pre_pull_image",
                description=(
                    f"Pre-pull {image} onto {node_id} so subsequent jobs start from "
                    f"cache, saving {saved_pulls} pulls ({saved_pulls * per_pull:.2f} GB)."
                ),
                proposed_action={
                    "kind": "pre_pull_image",
                    "node_id": node_id,
                    "image": image,
                    "eliminated_pulls": saved_pulls,
                    "eliminated_gb": round(saved_pulls * per_pull, 6),
                },
                rationale=(
                    "One scheduled pre-pull keeps the image in the node's cache, so "
                    "every subsequent job launch hits cache instead of pulling."
                ),
                source="detector:image_churn:pre_pull",
                claim=self._quantity_claim(
                    f"{node_id}:{image}", saved_pulls * per_pull,
                    f"{saved_pulls} redundant pulls of {per_pull:.2f} GB each.",
                ),
                traffic_kind="cross_az",
            )
        )

        node_zones = self._node_zones(dataset)
        node_zone = node_zones.get(node_id, "")
        if node_zone:
            candidates.append(
                ResourceCandidate(
                    kind="registry_mirror",
                    description=(
                        f"Deploy a registry mirror in {node_zone} so image pulls for "
                        f"{image} on {node_id} are local and faster."
                    ),
                    proposed_action={
                        "kind": "registry_mirror",
                        "node_id": node_id,
                        "image": image,
                        "zone": node_zone,
                        "eliminated_gb": round(total_gb * 0.7, 6),
                    },
                    rationale=(
                        "A zone-local mirror serves cached layers, cutting both transfer "
                        "cost and pull latency; 70% reduction is conservative because "
                        "unique layers still pull from origin."
                    ),
                    source="detector:image_churn:mirror",
                    claim=self._quantity_claim(
                        f"{node_id}:{image}", total_gb * 0.7,
                        f"70% of {total_gb:.2f} GB churn via a zone-local mirror.",
                    ),
                    traffic_kind="cross_az",
                )
            )
        return candidates

    # ------------------------------------------------------------ validation

    def validate_candidate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        checked = ["claimed_gb_positive", "resource_exists_in_dataset"]
        violations: list[str] = []

        claimed_gb = candidate.claim.quantity(Meter.GB_TRANSFERRED)
        if claimed_gb <= 0:
            violations.append("Candidate claims no measurable GB transferred")

        ev = observation.evidence
        if observation.signal_type is OpportunityType.CROSS_AZ_TRAFFIC:
            checked.append("zones_differ")
            src = str(ev.get("src_zone") or "")
            dst = str(ev.get("dst_zone") or "")
            if src and dst and src == dst:
                violations.append(
                    f"Source and destination are the same zone ({src}); no cross-zone cost"
                )

        elif observation.signal_type is OpportunityType.DATA_LOCALITY:
            checked += ["job_exists", "data_zone_has_nodes"]
            job = dataset.job_by_id().get(observation.resource_id)
            if job is None and observation.affected_job_ids:
                job = dataset.job_by_id().get(observation.affected_job_ids[0])
            if job is None:
                violations.append(
                    f"Job {observation.resource_id} is not in the cluster dataset"
                )
            src_zone = str(ev.get("src_zone") or "")
            nodes_in_src = ev.get("nodes_in_src_zone") or []
            if src_zone and not nodes_in_src:
                violations.append(
                    f"No known nodes in {src_zone}; cannot prove job could have been local"
                )

        elif observation.signal_type is OpportunityType.IMAGE_PULL_CHURN:
            checked += ["pull_count_above_threshold", "image_size_nonzero"]
            pull_count = int(ev.get("pull_count") or 0)
            if pull_count < MIN_CHURN_PULLS:
                violations.append(
                    f"Only {pull_count} pull(s) observed; minimum is {MIN_CHURN_PULLS}"
                )
            total_gb = float(ev.get("total_gb") or 0.0)
            if total_gb <= 0:
                violations.append("Image pulls report zero GB; cannot claim a saving")

        return checked, violations

    # ---------------------------------------------------------- presentation

    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        gb = candidate.claim.quantity(Meter.GB_TRANSFERRED)
        hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        gb_month = (gb / hours) * per_month if hours > 0 else 0.0
        rate = self.pricing.rate_for(
            Meter.GB_TRANSFERRED, kind=candidate.traffic_kind
        )
        dollars = gb_month * rate
        money = f"{gb_month:,.0f} GB/month (${dollars:,.0f}/month)"
        ev = observation.evidence
        action = candidate.proposed_action or {}

        if observation.signal_type is OpportunityType.CROSS_AZ_TRAFFIC:
            head = (
                f"Co-locate the endpoints behind the {float(ev.get('total_gb') or 0):.1f} GB "
                f"{ev.get('dominant_kind', 'cross-AZ')} flow between "
                f"{ev.get('src_zone')} and {ev.get('dst_zone')}, worth {money}"
            )
        elif observation.signal_type is OpportunityType.DATA_LOCALITY:
            head = (
                f"Schedule job {observation.resource_id} in {ev.get('src_zone')} where its "
                f"data lives, or replicate the data into {ev.get('dst_zone')}, worth {money}"
            )
        else:
            head = (
                f"Pre-pull image {ev.get('image')} onto node {ev.get('node_id')} or deploy a "
                f"zone-local registry mirror — {int(ev.get('pull_count') or 0)} redundant pulls, "
                f"worth {money}"
            )
        return (
            f"{head}. Confirm with the platform team first. Requires human "
            "approval; Natilah changes nothing."
        )

    # --------------------------------------------------------------- helpers

    def _quantity_claim(
        self, resource_id: str, gb: float, basis: str
    ) -> ResourceClaim:
        return ResourceClaim(
            quantities=[
                ResourceQuantity(
                    meter=Meter.GB_TRANSFERRED,
                    resource_id=resource_id,
                    amount=gb,
                )
            ],
            basis=basis,
            primary_meter=Meter.GB_TRANSFERRED,
        )

    @staticmethod
    def _node_zones(dataset: ClusterDataset) -> dict[str, str]:
        zones: dict[str, str] = {}
        for node in dataset.nodes:
            zone = (node.labels or {}).get(
                "topology.kubernetes.io/zone",
                (node.labels or {}).get("zone", ""),
            )
            if zone:
                zones[node.node_id] = zone
        for facility in dataset.facilities:
            for nid in facility.node_ids:
                zones.setdefault(nid, facility.zone)
        return zones
