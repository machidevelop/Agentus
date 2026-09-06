"""Turn heuristic confidence into a calibrated probability.

Every agent scores its own confidence from stated factors, and those scores are
comparable in the sense that they are built the same way. What they have never
been is *calibrated*: nothing checked whether findings scored 0.9 were actually
right nine times in ten. Until that check exists, ranking by expected value is
ranking by an untested number, and the confidence shown to a reviewer means
only "this agent felt good about it".

This module closes that loop with the outcomes the product already collects.
A reviewer approves or dismisses an action, and later the predicted saving is
either measured or it is not. Those verdicts are labels. Given enough of them:

    reliability     for each band of raw scores, how often findings in that band
                    were actually confirmed
    isotonic fit    a monotonic mapping from raw score to observed hit rate,
                    fitted with pool-adjacent-violators
    shrinkage       per-agent curves pulled toward the fleet-wide curve in
                    proportion to how little data the agent has

The last one matters more than it looks. A new agent with nine outcomes should
not get its own confident calibration curve; it should mostly inherit the
fleet's and earn its own as evidence accumulates.

Two scores report how well calibration is doing, and both are published rather
than kept internal: Brier score (lower is better, it is a mean squared error on
probabilities) and expected calibration error (the average gap between claimed
and observed rates).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Below this many outcomes an agent has no curve of its own and leans entirely
# on the fleet-wide one.
MIN_OUTCOMES_FOR_OWN_CURVE = 25

# Strength of the pull toward the fleet curve, in units of outcomes. An agent
# with exactly this many outcomes sits halfway between its own curve and the
# fleet's.
SHRINKAGE_STRENGTH = 40.0

# Laplace smoothing, so a bin holding one confirmed finding does not claim 1.0.
PRIOR_STRENGTH = 2.0
PRIOR_RATE = 0.5

DEFAULT_BINS = 10


@dataclass(frozen=True)
class Outcome:
    """One reviewed finding, with what actually happened to it.

    `confirmed` is the label: the reviewer accepted the finding as real, or a
    measurement later showed the predicted saving appeared. A dismissed finding
    is a negative label. Findings nobody has judged yet are not outcomes and
    must never be passed in as one.
    """

    finding_id: str
    agent_name: str
    raw_confidence: float
    confirmed: bool
    objective: str = ""


@dataclass
class ReliabilityBin:
    lower: float
    upper: float
    count: int = 0
    confirmed: int = 0
    mean_predicted: float = 0.0

    @property
    def observed_rate(self) -> float:
        """Smoothed hit rate, so a thin bin cannot claim certainty."""
        return (self.confirmed + PRIOR_STRENGTH * PRIOR_RATE) / (self.count + PRIOR_STRENGTH)

    @property
    def raw_rate(self) -> float:
        return self.confirmed / self.count if self.count else 0.0

    @property
    def gap(self) -> float:
        return abs(self.mean_predicted - self.raw_rate)


@dataclass
class CalibrationCurve:
    """A monotonic map from raw confidence to observed hit rate."""

    bins: list[ReliabilityBin] = field(default_factory=list)
    fitted: list[float] = field(default_factory=list)
    total: int = 0
    confirmed: int = 0

    @property
    def base_rate(self) -> float:
        if not self.total:
            return PRIOR_RATE
        return (self.confirmed + PRIOR_STRENGTH * PRIOR_RATE) / (self.total + PRIOR_STRENGTH)

    def apply(self, raw: float) -> float:
        """Map a raw score through the fitted curve, interpolating between bins."""
        if not self.fitted:
            return raw
        raw = max(0.0, min(1.0, raw))
        n = len(self.fitted)
        position = raw * n - 0.5
        low = math.floor(position)
        frac = position - low
        if low < 0:
            return self.fitted[0]
        if low >= n - 1:
            return self.fitted[-1]
        return self.fitted[low] * (1 - frac) + self.fitted[low + 1] * frac


class ConfidenceCalibrator:
    """Fits calibration curves from outcomes and applies them to new findings."""

    def __init__(self, bins: int = DEFAULT_BINS):
        self.bins = max(2, bins)
        self.fleet = CalibrationCurve()
        self.per_agent: dict[str, CalibrationCurve] = {}
        self._agent_totals: dict[str, int] = {}

    # --------------------------------------------------------------- fitting

    def fit(self, outcomes: list[Outcome]) -> ConfidenceCalibrator:
        """Fit the fleet curve and a curve per agent that has earned one."""
        usable = [o for o in outcomes if 0.0 <= o.raw_confidence <= 1.0]
        self.fleet = self._fit_curve(usable)
        self.per_agent = {}
        self._agent_totals = {}

        by_agent: dict[str, list[Outcome]] = {}
        for outcome in usable:
            by_agent.setdefault(outcome.agent_name, []).append(outcome)
        for agent, records in by_agent.items():
            self._agent_totals[agent] = len(records)
            if len(records) >= MIN_OUTCOMES_FOR_OWN_CURVE:
                self.per_agent[agent] = self._fit_curve(records)
        return self

    def _fit_curve(self, outcomes: list[Outcome]) -> CalibrationCurve:
        curve = CalibrationCurve()
        if not outcomes:
            return curve

        width = 1.0 / self.bins
        curve.bins = [
            ReliabilityBin(lower=i * width, upper=(i + 1) * width) for i in range(self.bins)
        ]
        sums = [0.0] * self.bins
        for outcome in outcomes:
            idx = min(self.bins - 1, int(outcome.raw_confidence / width))
            b = curve.bins[idx]
            b.count += 1
            b.confirmed += int(outcome.confirmed)
            sums[idx] += outcome.raw_confidence
        for i, b in enumerate(curve.bins):
            b.mean_predicted = sums[i] / b.count if b.count else (b.lower + b.upper) / 2.0

        curve.total = len(outcomes)
        curve.confirmed = sum(1 for o in outcomes if o.confirmed)
        curve.fitted = self._pava(
            [b.observed_rate for b in curve.bins],
            [float(b.count) + PRIOR_STRENGTH for b in curve.bins],
        )
        return curve

    @staticmethod
    def _pava(values: list[float], weights: list[float]) -> list[float]:
        """Pool adjacent violators: the least-squares monotonic fit.

        Confidence must not go down as the raw score goes up. Where the data
        says otherwise, the offending neighbours are pooled into their weighted
        mean until the sequence is non-decreasing.
        """
        blocks: list[tuple[float, float]] = []  # (value, weight)
        for value, weight in zip(values, weights):
            blocks.append((value, weight))
            while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
                v2, w2 = blocks.pop()
                v1, w1 = blocks.pop()
                total = w1 + w2
                blocks.append(((v1 * w1 + v2 * w2) / total, total))
        out: list[float] = []
        i = 0
        for value, weight in blocks:
            # Each pooled block covers however many original bins it absorbed.
            span = 0
            remaining = weight
            while i < len(weights) and remaining > 1e-9:
                remaining -= weights[i]
                span += 1
                i += 1
            out.extend([value] * max(span, 1))
        return out[: len(values)]

    # -------------------------------------------------------------- applying

    def calibrate(self, raw_confidence: float, agent_name: str = "") -> float:
        """Calibrated probability for one finding.

        An agent with its own curve is blended toward the fleet curve according
        to how much evidence it has, so a young agent inherits the fleet's
        behaviour and grows into its own.
        """
        raw = max(0.0, min(1.0, raw_confidence))
        if not self.fleet.fitted:
            return raw

        fleet_value = self.fleet.apply(raw)
        curve = self.per_agent.get(agent_name)
        if curve is None:
            return round(fleet_value, 4)

        n = float(self._agent_totals.get(agent_name, 0))
        weight = n / (n + SHRINKAGE_STRENGTH)
        blended = weight * curve.apply(raw) + (1.0 - weight) * fleet_value
        return round(max(0.0, min(1.0, blended)), 4)

    def is_fitted(self) -> bool:
        return bool(self.fleet.fitted)

    # --------------------------------------------------------------- quality

    def brier_score(self, outcomes: list[Outcome], calibrated: bool = True) -> float:
        """Mean squared error of the probabilities. Lower is better."""
        if not outcomes:
            return 0.0
        total = 0.0
        for o in outcomes:
            p = self.calibrate(o.raw_confidence, o.agent_name) if calibrated else o.raw_confidence
            total += (p - float(o.confirmed)) ** 2
        return round(total / len(outcomes), 6)

    def expected_calibration_error(
        self, outcomes: list[Outcome], calibrated: bool = True
    ) -> float:
        """Average gap between the probability claimed and the rate observed."""
        if not outcomes:
            return 0.0
        width = 1.0 / self.bins
        buckets: dict[int, list[tuple[float, bool]]] = {}
        for o in outcomes:
            p = self.calibrate(o.raw_confidence, o.agent_name) if calibrated else o.raw_confidence
            buckets.setdefault(min(self.bins - 1, int(p / width)), []).append((p, o.confirmed))
        error = 0.0
        for entries in buckets.values():
            mean_p = sum(p for p, _ in entries) / len(entries)
            rate = sum(1 for _, c in entries if c) / len(entries)
            error += (len(entries) / len(outcomes)) * abs(mean_p - rate)
        return round(error, 6)

    def report(self, outcomes: list[Outcome] | None = None) -> dict:
        """Everything a reviewer needs to judge whether to trust the scores."""
        data = {
            "fitted": self.is_fitted(),
            "outcomes_used": self.fleet.total,
            "base_rate": round(self.fleet.base_rate, 4),
            "agents_with_own_curve": sorted(self.per_agent),
            "agent_outcome_counts": dict(sorted(self._agent_totals.items())),
            "reliability": [
                {
                    "band": f"{b.lower:.1f}-{b.upper:.1f}",
                    "count": b.count,
                    "mean_predicted": round(b.mean_predicted, 4),
                    "observed_rate": round(b.raw_rate, 4),
                    "calibrated_to": round(self.fleet.fitted[i], 4)
                    if i < len(self.fleet.fitted)
                    else None,
                }
                for i, b in enumerate(self.fleet.bins)
                if b.count
            ],
        }
        if outcomes:
            data["brier_before"] = self.brier_score(outcomes, calibrated=False)
            data["brier_after"] = self.brier_score(outcomes, calibrated=True)
            data["ece_before"] = self.expected_calibration_error(outcomes, calibrated=False)
            data["ece_after"] = self.expected_calibration_error(outcomes, calibrated=True)
        return data


def outcomes_from_rows(rows) -> list[Outcome]:
    """Build labels from persisted findings that a reviewer has judged.

    Approved is a positive label and dismissed is a negative one. Anything
    still pending is not a label and is skipped, because treating unreviewed
    findings as failures would punish agents for a reviewer's backlog.
    """
    labels: list[Outcome] = []
    for row in rows:
        status = str(getattr(row, "status", "") or "").lower()
        if status not in {"approved", "dismissed", "verified", "rejected"}:
            continue
        labels.append(
            Outcome(
                finding_id=str(getattr(row, "opportunity_id", "")),
                agent_name=str(getattr(row, "agent_name", "") or ""),
                raw_confidence=float(getattr(row, "confidence_score", 0.0) or 0.0),
                confirmed=status in {"approved", "verified"},
                objective=str(getattr(row, "objective", "") or ""),
            )
        )
    return labels
