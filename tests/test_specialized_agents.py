from __future__ import annotations

import pytest

from natilah.agents.coordinator import default_agents
from natilah.agents.fragmentation_agent import FragmentationPlacementAgent
from natilah.agents.idle_allocation_agent import IdleAllocationAgent
from natilah.agents.over_allocation_agent import OverAllocationAgent
from natilah.agents.queue_efficiency_agent import QueueEfficiencyAgent
from natilah.engine.history import HistoricalPatternIndex
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import ClusterDataset
from natilah.models.enums import AgentObjective, CandidateOutcome


AGENT_CLASSES = [
    IdleAllocationAgent,
    OverAllocationAgent,
    QueueEfficiencyAgent,
    FragmentationPlacementAgent,
]


def run_agent(agent_cls, dataset: ClusterDataset):
    agent = agent_cls(use_llm=False)
    reconstructor = ClusterStateReconstructor(dataset)
    history = HistoricalPatternIndex(dataset)
    findings = agent.analyze_dataset(dataset, reconstructor=reconstructor, history=history)
    return agent, findings


def test_one_agent_per_objective():
    agents = default_agents(use_llm=False)
    objectives = {agent.objective for agent in agents}
    assert objectives == set(AgentObjective)
    assert len(agents) == len(objectives)


@pytest.mark.parametrize("agent_cls", AGENT_CLASSES)
def test_agents_emit_the_shared_structured_contract(agent_cls, synthetic_dataset: ClusterDataset):
    agent, findings = run_agent(agent_cls, synthetic_dataset)
    assert findings, f"{agent.name} produced no findings on the synthetic cluster"

    for finding in findings:
        # observed decision X
        assert finding.decision.job_id
        assert finding.description
        # alternative decision Y, deterministically validated
        assert finding.alternative.proposed_action
        assert finding.alternative.constraints_satisfied
        assert finding.agent_name == agent.name
        assert finding.objective == agent.objective
        assert finding.opportunity_type in agent.signal_types
        # expected recovery, priced from an explicit claim
        assert finding.claim.gpu_hours > 0
        assert finding.claim.basis
        assert finding.value.gpu_hours_recovered == pytest.approx(finding.claim.gpu_hours)
        assert finding.value.estimated_monthly_value > 0
        assert finding.value.assumptions
        # queue or utilization impact
        assert finding.comparison.actual is not None
        assert finding.comparison.alternative is not None
        # confidence and evidence
        assert 0.0 < finding.confidence.score <= 1.0
        assert finding.confidence.constraints_checked
        assert finding.evidence["tools"]
        assert finding.evidence["objective"] == agent.objective.value
        # actionable by an engineer, execution stays human-approved
        assert "human approval" in finding.recommended_action
        # every candidate considered is recorded, selected one included
        assert finding.candidates_considered
        outcomes = {c.outcome for c in finding.candidates_considered}
        assert CandidateOutcome.SELECTED in outcomes


@pytest.mark.parametrize("agent_cls", AGENT_CLASSES)
def test_claims_never_exceed_what_the_decision_could_release(agent_cls, synthetic_dataset):
    agent, findings = run_agent(agent_cls, synthetic_dataset)
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    history = HistoricalPatternIndex(synthetic_dataset)
    for finding in findings:
        observation = next(
            obs
            for obs in agent.detect(synthetic_dataset, reconstructor)
            if obs.decision.job_id == finding.decision.job_id
        )
        ctx = agent.build_context(observation, synthetic_dataset, reconstructor, history)
        assert ctx is not None
        assert finding.claim.gpu_hours <= agent.claim_cap_gpu_hours(ctx) * 1.001


def test_selected_candidate_is_the_highest_value_feasible_one(synthetic_dataset):
    _, findings = run_agent(OverAllocationAgent, synthetic_dataset)
    multi = [f for f in findings if len(f.candidates_considered) > 1]
    assert multi, "over-allocation agent should generate multiple sizing candidates"
    for finding in multi:
        feasible = [
            c
            for c in finding.candidates_considered
            if c.outcome in {CandidateOutcome.FEASIBLE, CandidateOutcome.SELECTED}
        ]
        selected = next(c for c in feasible if c.outcome == CandidateOutcome.SELECTED)
        best = max(c.monthly_value * c.confidence_score for c in feasible)
        assert selected.monthly_value * selected.confidence_score == pytest.approx(best)


def test_infeasible_candidates_are_rejected_with_a_reason(synthetic_dataset):
    agent, findings = run_agent(QueueEfficiencyAgent, synthetic_dataset)
    assert agent.summary.candidates_rejected_infeasible > 0
    rejected = [
        c
        for f in findings
        for c in f.candidates_considered
        if c.outcome == CandidateOutcome.INFEASIBLE
    ]
    for candidate in rejected:
        assert candidate.violations
        assert candidate.rejection_reason
        assert candidate.monthly_value == 0.0


def test_fragmentation_agent_requires_a_consumer_for_freed_capacity(synthetic_dataset):
    _, findings = run_agent(FragmentationPlacementAgent, synthetic_dataset)
    for finding in findings:
        # Rearranging GPUs only pays if a real waiting job could use the result.
        assert finding.claim.queue_job_ids
        assert finding.claim.queue_seconds > 0


def test_idle_agent_only_claims_gpus_that_did_no_work(synthetic_dataset):
    agent, findings = run_agent(IdleAllocationAgent, synthetic_dataset)
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    history = HistoricalPatternIndex(synthetic_dataset)
    observations = agent.detect(synthetic_dataset, reconstructor)
    for finding in findings:
        observation = next(o for o in observations if o.decision.job_id == finding.decision.job_id)
        ctx = agent.build_context(observation, synthetic_dataset, reconstructor, history)
        means = agent._window_means(ctx, ctx.hold_window())
        for interval in finding.claim.intervals:
            assert means.get(interval.gpu_id, 0.0) < 5.0
