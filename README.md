# Natilah V1

Read-only AI infrastructure intelligence layer for GPU compute economics.

Natilah observes existing scheduler decisions, reconstructs cluster context, generates feasible counterfactual alternatives, and quantifies recoverable compute value. It never modifies infrastructure.

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Generate synthetic demo data
python scripts/generate_demo_data.py

# Run the intelligence pipeline
python scripts/run_analysis.py

# Launch the dashboard
uvicorn natilah.api.app:app --port 8000
# Open http://localhost:8000
```

## Architecture

```
Data Ingestion → Normalized Model → State Reconstructor → Signal Detectors
→ Specialized Agents (one per optimization objective)
     idle allocation | over-allocation | queue efficiency | fragmentation & placement
   each: investigate with read-only tools → draft multiple alternatives Y
         → validate each deterministically → simulate → price from an explicit
           GPU-hour claim → score confidence → keep the highest-value feasible Y
→ Coordination Layer (deduplicate GPU-hours, resolve conflicts, rank by value)
→ REST API → Dashboard
```

Every agent emits the same structured record: the observed decision X, the
alternatives Y it considered (including the rejected ones and why), the
constraints checked, GPU-hours recovered, queue and utilization impact,
financial value, a confidence score, and the supporting evidence.

The coordination layer credits each GPU-hour once, drops actions that
contradict a higher-value one, and ranks what remains by expected monthly
value. `GET /api/actions` returns the top independently validated actions.

**Agent mode:** Hybrid. Deterministic tools always run; when `XAI_API_KEY` is
set the LLM additionally selects tools to investigate with and drafts extra
candidate alternatives. It never simulates the cluster, prices a finding, or
decides feasibility — every candidate it returns is re-validated against
reconstructed state.

**Execution:** always human-approved. `POST /api/actions/{id}/status` records an
engineer's decision; Natilah performs no infrastructure change.

## Two fleets, one engine

The engine is domain-neutral: an observed decision X, feasible alternatives Y,
deterministic validation, an explicit claim in one meter, and a ledger that
credits each unit once. Nothing in that is specific to GPUs, so it runs a
consumer fleet as well as a cluster fleet.

| Fleet | Dataset | Agents | Meters |
|---|---|---|---|
| Cluster | `ClusterDataset` | 10 agents (scheduling, storage, network, commitments, power, training, inference) | GPU-hours, queue-seconds, GB-months, GB, kWh, $ committed, replica-hours |
| Household | `HouseholdDataset` | `claim_recovery_agent`, `recurring_spend_agent` | claim-dollars, recurring-dollars |

Consumer meters are dollars, so the rate is 1.0 and the claim quantity is the
money itself. Two kinds of money are kept apart and never summed into one
headline:

- **one-time** — a denied claim recovered once. Reported as `one_time_value`.
- **recurring** — a subscription that bills every month until it is stopped.
  Reported as `estimated_monthly_value`, and never normalized against the
  length of the observation window.

```bash
# Ranked household actions from a synthetic household
python scripts/run_household_analysis.py

# Or from a real export
python scripts/run_household_analysis.py path/to/export.json --json
```

Over the API, `GET /api/household/demo` runs the synthetic household and
`POST /api/household/analyze` takes an export as a file upload. Both are
stateless: claim lines are read, used, and discarded, never persisted.

## Ranking quality

Two things decide whether the ranked list is worth reading.

**Global conflict selection** (`natilah/engine/selection.py`). Two findings
conflict when they cannot both be applied. Picking greedily by value is wrong
whenever one large finding blocks two medium ones worth more together:

```
A ($900) conflicts with B ($600) and C ($550); B and C do not conflict.
greedy keeps A          -> $900
maximum-weight set {B,C} -> $1,150
```

The coordinator solves maximum-weight independent set per connected component,
exactly for small components and by local search for large ones, and every
dropped finding records which selected findings displaced it. The report field
`selection_gain_monthly_value` says what this recovered over greedy.

**Confidence calibration** (`natilah/engine/calibration.py`). Agent confidence
was a heuristic that nothing had ever checked against outcomes. Reviewer
decisions are labels, so they fit a monotonic calibration curve
(pool-adjacent-violators) per agent, shrunk toward the fleet-wide curve in
proportion to how little data each agent has. `ConfidenceAssessment` keeps both
`raw_score` and the calibrated `score`. Quality is measured and published, not
asserted: on a synthetic overconfident agent, expected calibration error drops
from 0.30 to 0.03.

Pass one in to enable it; without it, confidence stays the agent's own
heuristic and nothing pretends otherwise:

```python
calibrator = ConfidenceCalibrator().fit(outcomes_from_rows(reviewed_findings))
AgentCoordinator(calibrator=calibrator)
```

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

```
DATABASE_URL=sqlite+aiosqlite:///./data/natilah.db
SAFETY_MODE=read_only
XAI_API_KEY=        # Optional: enables LLM-augmented alternative generation
XAI_MODEL=grok-4.6
AGENT_MODE=hybrid
```

## Tests

```bash
pytest tests/ -v
```

## Project Status

- **V1 MVP:** Complete. Synthetic data demo works end-to-end.
- **Specialized agents + coordination layer:** Complete. Objective-specific
  agents, deterministic validation per candidate, per-meter deduplication and
  global conflict selection across agents, ranked actions API.
- **Consumer fleet:** Complete and read-only. Health claim recovery and
  recurring household spend, on the same engine and the same output contract.
  Not yet validated against real claim data.
- **Confidence calibration:** Implemented; needs real reviewer outcomes to fit
  against. Uncalibrated until those exist.
- **Next milestone:** Run the pipeline on 7+ days of real Slurm or Kubernetes
  telemetry and have an engineer review the top 20 actions.
- **Out of scope:** Authentication, export, autonomous execution, energy agents.

## Safety

Natilah operates in `READ_ONLY` mode. It cannot modify scheduler configs, move workloads, terminate jobs, or execute infrastructure changes. The safety guard layer explicitly blocks all mutation operations.
