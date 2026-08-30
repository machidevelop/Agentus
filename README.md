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
- **Specialized agents + coordination layer:** Complete. Four objective-specific
  agents, deterministic validation per candidate, GPU-hour deduplication and
  conflict resolution across agents, ranked actions API.
- **Next milestone:** Run the pipeline on 7+ days of real Slurm or Kubernetes
  telemetry and have an engineer review the top 20 actions.
- **Out of scope:** Authentication, export, autonomous execution, energy agents.

## Safety

Natilah operates in `READ_ONLY` mode. It cannot modify scheduler configs, move workloads, terminate jobs, or execute infrastructure changes. The safety guard layer explicitly blocks all mutation operations.
