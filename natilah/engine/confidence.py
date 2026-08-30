"""Confidence and explainability for X vs Y. Not a claim of optimality."""

from __future__ import annotations

from statistics import mean, pstdev

from natilah.models.domain import (
    Alternative,
    ClusterDataset,
    ConfidenceAssessment,
    ConfidenceFactor,
    Observation,
)
from natilah.models.enums import ConfidenceLevel


class ConfidenceScorer:
    def assess(
        self,
        observation: Observation,
        alternative: Alternative,
        dataset: ClusterDataset,
        constraints_checked: list[str],
        similar_count: int = 0,
    ) -> ConfidenceAssessment:
        samples = [
            sample
            for job_id in set(observation.affected_job_ids)
            for sample in dataset.samples_for_job(job_id)
        ]
        completeness = 1.0 if samples else 0.2
        if observation.affected_gpu_ids:
            covered = {s.gpu_id for s in samples}
            completeness = min(1.0, len(covered) / max(len(observation.affected_gpu_ids), 1))

        if samples:
            utils = [s.gpu_utilization_pct for s in samples]
            sigma = pstdev(utils) if len(utils) > 1 else 0.0
            # Low variance with a clear idle/active split is a strong signal.
            signal = max(0.0, min(1.0, 1.0 - sigma / 50.0))
            signal_reason = f"Utilization σ={sigma:.1f} across {len(utils)} samples"
        else:
            signal = 0.3
            signal_reason = "No utilization samples for the affected GPUs"

        coverage = min(1.0, len(constraints_checked) / 6.0)
        feasibility = 0.85 if alternative.proposed_action else 0.2
        historical = min(1.0, 0.4 + 0.2 * similar_count)

        factors = [
            ConfidenceFactor(
                name="data_completeness",
                weight=0.20,
                score=completeness,
                reason="Full utilization data available" if completeness >= 0.8 else "Partial utilization coverage",
            ),
            ConfidenceFactor(
                name="utilization_signal_strength",
                weight=0.25,
                score=signal,
                reason=signal_reason,
            ),
            ConfidenceFactor(
                name="constraint_coverage",
                weight=0.20,
                score=coverage,
                reason=f"{len(constraints_checked)} operational constraints evaluated",
            ),
            ConfidenceFactor(
                name="alternative_feasibility",
                weight=0.20,
                score=feasibility,
                reason="Alternative passed hard constraint validation",
            ),
            ConfidenceFactor(
                name="historical_consistency",
                weight=0.15,
                score=historical,
                reason=f"Pattern observed in {similar_count} similar job(s)" if similar_count else "Single occurrence in this window",
            ),
        ]
        score = sum(f.weight * f.score for f in factors)
        if score >= 0.75:
            level = ConfidenceLevel.HIGH
        elif score >= 0.50:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        assumptions = [
            "Observed utilization is representative of the job's true compute demand.",
            "No unobserved constraint (licenses, locality, topology beyond NVLink) blocked Y.",
            "Y is a feasible counterfactual, not a recommended production change.",
        ]
        uncertainty = []
        if completeness < 0.8:
            uncertainty.append("Incomplete telemetry for some allocated GPUs")
        if similar_count == 0:
            uncertainty.append("Pattern has not been shown to recur")
        if not samples:
            uncertainty.append("Alternative relies on reconstructed occupancy without utilization proof")

        explanation = (
            f"{alternative.agent_rationale} Compared with the observed decision, this alternative "
            f"is expected to differ because {observation.description} "
            f"Confidence is {level.value} ({score:.2f})."
        )
        return ConfidenceAssessment(
            score=round(score, 4),
            level=level,
            factors=factors,
            assumptions=assumptions,
            constraints_checked=constraints_checked,
            uncertainty_sources=uncertainty,
            explanation=explanation,
        )
