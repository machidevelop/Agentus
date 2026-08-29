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
Data Ingestion → Normalized Model → State Reconstructor → Opportunity Detectors
→ Counterfactual Validator → Comparator → Value Calculator → Confidence Scorer
→ REST API → Dashboard
```

**Agent mode:** Hybrid (tool-synthesized candidates + optional LLM reasoning via xAI when `XAI_API_KEY` is set).

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
- **Next milestone:** Read-only Slurm connector for real cluster history (7+ days).
- **Out of scope (V1):** Authentication, export, autonomous execution, energy agents.

## Safety

Natilah operates in `READ_ONLY` mode. It cannot modify scheduler configs, move workloads, terminate jobs, or execute infrastructure changes. The safety guard layer explicitly blocks all mutation operations.
