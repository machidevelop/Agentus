"""Confidence calibration against recorded reviewer outcomes."""

from __future__ import annotations

import random

import pytest

from natilah.engine.calibration import (
    MIN_OUTCOMES_FOR_OWN_CURVE,
    ConfidenceCalibrator,
    Outcome,
    outcomes_from_rows,
)


def _overconfident(n: int = 500, seed: int = 3, agent: str = "claim_recovery_agent"):
    """An agent that claims high confidence and is right far less often."""
    rng = random.Random(seed)
    outcomes = []
    for i in range(n):
        raw = rng.uniform(0.5, 1.0)
        # True probability rises with the raw score but sits well below it.
        true_p = 0.15 + 0.55 * (raw - 0.5) / 0.5
        outcomes.append(Outcome(f"f{i}", agent, raw, rng.random() < true_p))
    return outcomes


def test_calibration_reduces_brier_and_calibration_error():
    outcomes = _overconfident()
    calibrator = ConfidenceCalibrator().fit(outcomes)
    report = calibrator.report(outcomes)

    assert report["brier_after"] < report["brier_before"]
    assert report["ece_after"] < report["ece_before"]
    # The systematic overconfidence should be mostly removed.
    assert report["ece_after"] < 0.10


def test_an_overconfident_score_is_pulled_down():
    calibrator = ConfidenceCalibrator().fit(_overconfident())
    assert calibrator.calibrate(0.95, "claim_recovery_agent") < 0.80


def test_calibration_is_monotonic():
    """A higher raw score must never calibrate to a lower probability."""
    calibrator = ConfidenceCalibrator().fit(_overconfident())
    values = [calibrator.calibrate(x / 20.0, "claim_recovery_agent") for x in range(21)]
    for earlier, later in zip(values, values[1:]):
        assert later >= earlier - 1e-9


def test_an_unfitted_calibrator_passes_scores_through_untouched():
    calibrator = ConfidenceCalibrator()
    assert not calibrator.is_fitted()
    assert calibrator.calibrate(0.83, "any_agent") == 0.83


def test_a_thin_agent_leans_on_the_fleet_curve():
    """A new agent with a handful of outcomes gets no curve of its own."""
    outcomes = _overconfident(agent="established_agent")
    outcomes += [
        Outcome(f"new{i}", "new_agent", 0.9, True) for i in range(MIN_OUTCOMES_FOR_OWN_CURVE - 5)
    ]
    calibrator = ConfidenceCalibrator().fit(outcomes)

    assert "established_agent" in calibrator.per_agent
    assert "new_agent" not in calibrator.per_agent
    # It inherits the fleet's correction rather than its own flattering record.
    assert calibrator.calibrate(0.9, "new_agent") < 0.9


def test_a_well_evidenced_agent_earns_its_own_curve():
    outcomes = _overconfident(agent="agent_a")
    rng = random.Random(9)
    # A second agent that is genuinely reliable at the same raw scores.
    outcomes += [
        Outcome(f"b{i}", "agent_b", 0.9, rng.random() < 0.92) for i in range(300)
    ]
    calibrator = ConfidenceCalibrator().fit(outcomes)

    assert {"agent_a", "agent_b"} <= set(calibrator.per_agent)
    # The reliable agent must not be dragged down to the unreliable one's rate.
    assert calibrator.calibrate(0.9, "agent_b") > calibrator.calibrate(0.9, "agent_a")


def test_smoothing_prevents_a_single_outcome_claiming_certainty():
    calibrator = ConfidenceCalibrator().fit([Outcome("only", "a", 0.95, True)])
    assert calibrator.calibrate(0.95, "a") < 1.0


def test_outcomes_are_only_built_from_reviewed_findings():
    class Row:
        def __init__(self, oid, status, score, agent="a"):
            self.opportunity_id = oid
            self.status = status
            self.confidence_score = score
            self.agent_name = agent
            self.objective = "claim_recovery"

    rows = [
        Row("1", "approved", 0.9),
        Row("2", "dismissed", 0.8),
        Row("3", "pending", 0.7),
        Row("4", "new", 0.6),
        Row("5", "verified", 0.95),
    ]
    outcomes = outcomes_from_rows(rows)

    # Unreviewed findings are not labels: a reviewer's backlog is not evidence.
    assert {o.finding_id for o in outcomes} == {"1", "2", "5"}
    assert {o.finding_id for o in outcomes if o.confirmed} == {"1", "5"}


def test_report_exposes_the_reliability_curve():
    outcomes = _overconfident()
    report = ConfidenceCalibrator().fit(outcomes).report(outcomes)

    assert report["fitted"] is True
    assert report["outcomes_used"] == len(outcomes)
    assert report["reliability"], "the reliability table is what makes this auditable"
    for band in report["reliability"]:
        assert 0.0 <= band["observed_rate"] <= 1.0
        assert band["count"] > 0


def test_calibrated_findings_keep_their_raw_score(synthetic_dataset):
    """Ranking uses the calibrated number; the audit trail keeps both."""
    from natilah.agents.coordinator import AgentCoordinator
    from natilah.agents.idle_allocation_agent import IdleAllocationAgent

    calibrator = ConfidenceCalibrator().fit(
        _overconfident(agent="idle_allocation_agent", n=300)
    )
    coordinator = AgentCoordinator(
        agents=[IdleAllocationAgent(use_llm=False)], calibrator=calibrator
    )
    findings, report = coordinator.analyze_dataset(synthetic_dataset)

    assert findings
    for finding in findings:
        assert finding.confidence.calibrated is True
        assert finding.confidence.raw_score is not None
        assert finding.confidence.score != pytest.approx(finding.confidence.raw_score)
    assert any("calibrated" in note.lower() for note in report.notes)
