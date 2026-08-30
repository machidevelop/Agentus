# Natilah — Product Vision

**Written: 2026-08-30.** Companion to `CURRENT_SITUATION.md` (which records what exists).
This file records what we are building toward and what still has to be true.

---

## 1. The idea

Agentus is a fleet of agents that live around a customer's AI infrastructure, each
watching one way money is wasted, each proposing a specific better decision backed
by real telemetry, and each priced in dollars.

Customers log into natilah.com and manage that fleet: turn agents on, configure
what each one optimizes for, set the guardrails, and read a single ranked list of
what to fix next. A cluster might run 4 agents or 20+ against the same workload —
scheduling, placement, storage, network, commitments, power — and the platform
guarantees the totals still add up.

**The fleet exists to cover everything, not to crowd one thing.** Twenty agents means
twenty *different* costs being watched — idle GPUs, cold checkpoints, cross-AZ traffic,
expiring reservations, capped clocks, dead endpoints — not twenty opinions about the
same idle GPU. Breadth is the product; redundancy is noise the coordination layer has
to delete. See #4.

Two modes, sold in order:

- **View mode** — agents observe and recommend. Humans decide. (Where we are.)
- **Act mode** — agents execute inside approved boundaries, with rollback and
  measured outcomes. (Where the business is.)

The bet: *the scheduler is not the product, the accounting is.* Anyone can point at
an idle GPU. Almost nobody can tell a CFO how many dollars are genuinely
recoverable without counting the same hour twice.

---

## 2. Why this is defensible

The moat is not the LLM and not the agents. It is three things underneath them:

1. **The claim ledger.** Every finding declares exactly which resources, over which
   window, it claims to recover. Overlapping claims are credited once. This is what
   lets 20 agents coexist without inflating the total, and it is the thing a
   customer's finance team can audit.
2. **Deterministic feasibility.** Every proposal is validated against reconstructed
   state — the GPUs existed, they were free, the constraints held, priority was not
   inverted. Rejected proposals are kept with reasons. An LLM drafts candidates; it
   never decides whether one was possible.
3. **Ingestion breadth.** Every new waste domain needs its own data source. That work
   is unglamorous, slow, and compounding — which is exactly what makes it a moat.

The LLM's job stays small on purpose: investigate evidence, choose which read-only
tools to run, draft candidate alternatives. It does not simulate infrastructure,
price findings, or judge feasibility.

---

## 3. What an "agent" is (the unit customers configure)

An agent is a declarative object, not a script:

| Part | Meaning | Customer-configurable? |
|---|---|---|
| Objective | The one thing it optimizes (e.g. idle allocation) | No — defines the agent |
| Signals | Detectors that wake it | Thresholds: yes |
| Tools | Read-only probes it may call | Allowlist: yes |
| Claim rule | Which resource-hours it may charge for | No — protects the ledger |
| Guardrails | Priority inversion, blast radius, protected namespaces, quiet hours | Yes |
| Economics | Cost per unit, amortization, facility multiplier | Yes |
| Mode | view / advise / act | Yes, per agent |

Adding an agent should be a manifest plus a claim rule, not a new pipeline. The
current four agents already share one base class and one output contract, which is
the shape this requires.

---

## 4. Core principle: one agent per meter — coverage, not redundancy

This is the design rule the rest of the roadmap follows.

**Agents that split the same resource redistribute credit; they do not create it.
Agents that watch a resource nobody was watching create all of it.**

Measured this week on a real 5,000-job A100 trace: four agents produced $927k/month
of *claimed* value; the coordination layer credited $458k/month. The over-allocation
agent found 177 genuine findings and was credited for 10 — the other 167 were the
same GPU-hours the idle agent had already claimed. Four agents, one meter, heavy
overlap. That is the ceiling of piling agents onto one resource, and it is low.

So the fleet grows sideways, not deeper. Every new agent should answer *"which cost
is currently invisible?"* — never *"who else can have an opinion about GPU-hours?"*
Twenty agents across twenty meters is a platform. Twenty agents on GPU-hours is four
agents plus sixteen duplicates the ledger will delete.

### Coverage map — the "everything" the fleet is meant to see

| Domain | Meter | Example agent | Status |
|---|---|---|---|
| Scheduling | GPU-hours | idle allocation | Built |
| Right-sizing | GPU-hours | over-allocation | Built |
| Queueing | queue-seconds | queue efficiency | Built |
| Placement | GPU-hours + contiguity | fragmentation/placement | Built |
| Storage | GB-months | orphaned volumes, cold checkpoints, snapshot sprawl | Not started |
| Network | GB transferred | cross-AZ traffic, data locality, image pull churn | Not started |
| Commitments | $ committed vs used | reservation coverage, spot eligibility, expiry | Not started |
| Power | kWh | clock caps, PUE-aware placement, off-peak shifting | Not started |
| Training efficiency | wasted GPU-hours | dataloader stalls, restart waste, non-converging sweeps | Not started |
| Inference | replica-hours | idle endpoints, over-provisioned replicas, batch headroom | Not started |
| Licensing | seat-hours | unused seats, wrong tier | Not started |
| Data pipeline | CPU-hours + GB | duplicate preprocessing, re-materialized datasets | Not started |

Four of twelve covered, and the four that are covered share one meter. The roadmap
in §6 Phase 3 is the plan for the other eight — each ships with its own connector,
its own meter, and its own claim rule, or it does not ship.

Corollary for pricing and for the dashboard: show customers claimed vs credited, and
never let a fleet's headline be the sum of its agents.

---

## 5. Where it is today

Working, and verified this week:

- Four specialized agents (idle allocation, over-allocation, queue efficiency,
  fragmentation/placement) sharing one candidate ladder and one output contract.
- Multiple alternatives drafted per decision, each deterministically validated;
  infeasible ones kept with reasons (300 rejected in the 5k-job run).
- Coordination layer: GPU-hour ledger, conflict resolution, single ranking.
- Value priced from explicit claims; confidence scored per finding (avg 0.958).
- Read-only enforcement end to end; approval is recorded, never executed.
- Connectors: Slurm, Kubernetes, Alibaba trace, synthetic, JSON upload.
- REST API including `/api/actions` (ranked), `/api/agents`, approval endpoint.
- 121 tests. Deterministic across runs. 2.5x faster after this week's profiling.

Not there yet:

- The dashboard is a template running on sample data — not wired to the API.
- Analysis is a batch re-scan over SQLite, single-tenant, no incremental updates.
- Agents are hard-coded classes; there is no manifest, registry, or config API.
- The claim ledger understands GPU-hours and queue-seconds only.
- Conflict resolution is pairwise supersede, not a global selection.
- No act mode, no execution adapters, no rollback, no outcome measurement.
- No validation on a real customer cluster — everything so far is public traces
  and synthetic data.
- Confidence is a heuristic never calibrated against measured outcomes.

---

## 6. To-do — path to the ideal product

### Phase 0 — Earn the right to sell view mode
- [ ] Capture 7–30 days of real Slurm or Kubernetes telemetry from a live cluster.
- [ ] Run the pipeline on it; have an experienced engineer review the top 20 actions.
- [ ] Gate: at least 15/20 confirmed feasible, no systematic hallucination pattern.
- [ ] Regenerate the canonical validation numbers post-alias-fix; retire the old ones.
- [ ] Record reviewer verdicts as labels — this is the first calibration data.

### Phase 1 — Wire the product that already exists
- [ ] Connect the dashboard to the live API; delete sample data paths.
- [ ] Action inbox: ranked list, filters by agent/objective/confidence/value.
- [ ] Action detail: observed X, chosen Y, rejected alternatives, evidence, claim.
- [ ] Approve / dismiss / snooze with reviewer identity and reason, exported.
- [ ] Show claimed vs credited everywhere; never display an un-deduplicated total.
- [ ] Continuous ingestion instead of one-shot; incremental analysis per window.
- [ ] Multi-tenant data model, per-customer isolation, retention policy, RBAC.

### Phase 2 — Make the fleet configurable
- [ ] Agent manifest format (objective, signals, thresholds, tools, guardrails, economics).
- [ ] Agent registry + versioning; enable/disable per cluster, per namespace, per queue.
- [ ] Config API + UI: thresholds, cost model, protected resources, quiet hours.
- [ ] Backtest-on-save: any config change is re-run against recent history and shows
      how findings and credited value shift before it is committed.
- [ ] Guard against noise: per-agent precision tracking, auto-suggest threshold changes.
- [ ] Generalize the ledger: pluggable resource meters (GPU-h, GB-month, GB egress,
      kWh, license-seat-hours) with per-meter dedup and per-meter pricing.
- [ ] Replace pairwise supersede with a global selection (max credited value subject
      to mutual-exclusion constraints); keep the explanation human-readable.
- [ ] Scale test: 20+ agents, 100k jobs, bounded runtime and memory.

### Phase 3 — Beyond scheduling (where new value actually lives)

Each item below is a *new meter*, not another view of GPU-hours. This phase, not the
agent count, is what makes the fleet worth twenty agents (see §4).
- [ ] Storage: orphaned volumes, cold checkpoints, snapshot sprawl, duplicate datasets.
- [ ] Network: cross-AZ traffic, egress from bad data locality, image pull churn.
- [ ] Commitments: reserved vs on-demand vs spot coverage, expiry, mismatch to usage.
- [ ] Power/thermal: capped GPUs, PUE-aware placement, off-peak shifting.
- [ ] Training efficiency: dataloader stalls, checkpoint frequency, restart waste,
      failed-run spend, hyperparameter sweeps that never converge.
- [ ] Inference: over-provisioned replicas, batch-size headroom, idle endpoints,
      model-parallel splits that do not pay for themselves.
- [ ] Each domain ships with its connector, its meter, and its claim rule. No domain
      ships without dedup.

### Phase 4 — Act mode
- [ ] Execution adapters per platform (Slurm, Kubernetes, cloud APIs), narrow scope.
- [ ] Policy engine: what may be acted on, by which agent, within what blast radius,
      during which windows, with what maximum reversible unit of change.
- [ ] Dry-run and staged rollout: one job, then one queue, then the cluster.
- [ ] Automatic rollback triggers and a hard kill switch per agent and per fleet.
- [ ] Immutable audit log: who or what changed X, on what evidence, with what result.
- [ ] Start with the class of actions that are cheap to reverse (release idle GPUs,
      resize a submission template) and never with preemption.
- [ ] Human-in-the-loop by default; autonomy earned per action class, per customer.

### Phase 5 — Prove the money
- [ ] Outcome measurement: did the predicted GPU-hours actually free up?
- [ ] Holdout or A/B design so savings are attributable, not asserted.
- [ ] Calibrate confidence against measured outcomes; publish reliability curves.
- [ ] Savings attestation report a finance team can sign off on.
- [ ] Fleet benchmarking: how this cluster compares to peers, anonymized.
- [ ] Only then: outcome-based pricing (share of verified savings) becomes credible.

---

## 7. The hard problems (do not underestimate these)

| Problem | Why it is hard | What failure looks like |
|---|---|---|
| Generalized claim accounting | Different meters, different units, different overlap semantics | Totals stop adding up; the audit story dies |
| Conflict selection at fleet scale | Combinatorial once actions have dependencies | Recommendations that cannot all be applied |
| Act-mode safety | Infrastructure is production; mistakes are outages | One bad action ends the company's reputation |
| Proving realized savings | Counterfactuals cannot be observed directly | Customer renews on faith, then does not renew |
| Config surface | Users can tune agents into noise | Alert fatigue, findings ignored, churn |
| Ingestion breadth | Every domain is a new integration | Product stalls at "GPU idle detector" |
| Trust ladder | Act mode requires earned permission | Selling autonomy too early kills the pilot |

---

## 8. Non-goals

- Replacing the scheduler. Natilah observes it and proposes; it does not become it.
- Autonomous action without an approval path, ever, by default.
- A generic FinOps dashboard. The product is decisions, not charts.
- Model quality, training accuracy, or research productivity. Cost and utilization only.

---

## 9. Open questions for the founder

1. **Which customer first?** Enterprise on-prem Slurm, K8s-native AI platform teams, or
   neocloud operators? Each implies a different first connector and a different buyer.
2. **What does the first act-mode action cost if it goes wrong?** That answer sets the
   entire guardrail design.
3. **Pricing:** flat platform fee, per-GPU, or share of verified savings? The last one
   is the strongest story and requires Phase 5 to exist first.
4. **Do customers want to author their own agents,** or configure ours? Authoring
   implies an SDK, a review process, and a much larger safety surface.
5. **How much waste is acceptable to a customer?** Some clusters are deliberately slack
   for burst capacity. The product must be able to be told that.

---

## 10. Verdict on feasibility

Yes — provided the fleet grows by coverage, not by crowding (§4). The agent base class,
shared output contract, and coordination layer already generalize to 20+ agents, and
each new agent is a manifest plus a claim rule. That is the easy half, and it only pays
off if those twenty agents are watching twenty different costs.

The hard half is what makes the fleet worth paying for: generalized claim accounting
across many meters, execution that cannot hurt production, and measured proof that the
predicted dollars actually appeared. Those three, not the agent count, decide whether
this becomes a platform or a very good report.
