# Natilah V1 — Detailed Technical Implementation Guide

This document specifies the exact, step-by-step implementation procedures for building **Natilah V1** — a read-only AI infrastructure intelligence layer.

---

## Phase 1: Foundation, Configuration & Domain Models

### Step 1.1: Project Environment & Configuration
* Create `pyproject.toml` and `requirements.txt` with pinned dependencies: `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy`, `aiosqlite`, `numpy`, `scipy`, `pytest`, `pytest-asyncio`, `httpx`.
* Create `natilah/config.py`:
  * Load environment variables via `Pydantic-Settings`.
  * Configuration fields: `DATABASE_URL` (default: `sqlite+aiosqlite:///./data/natilah.db`), `SAFETY_MODE` (default: `"read_only"`), `LOG_LEVEL`, `DEFAULT_COST_PER_GPU_HOUR`.

### Step 1.2: Domain Enumerations
* Create `natilah/models/enums.py`:
  * `JobState`: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`
  * `DecisionType`: `ALLOCATE`, `PLACE`, `QUEUE`, `CONSOLIDATE`
  * `OpportunityType`: `OVER_ALLOCATION`, `POOR_PLACEMENT`, `FRAGMENTATION`, `IDLE_ALLOCATION`, `QUEUE_INEFFICIENCY`
  * `ConfidenceLevel`: `HIGH`, `MEDIUM`, `LOW`
  * `SafetyMode`: `READ_ONLY`, `PROPOSE`, `EXECUTE_WITH_APPROVAL`

### Step 1.3: Pydantic Domain Models
* Create `natilah/models/domain.py`:
  * Define schema for `GPUType`, `GPU`, `Node`, `Job`, `Allocation`, `GPUUtilizationSample`, `QueueSnapshot`, `SchedulerDecision`, `ClusterStateSnapshot`, `Opportunity`, `Alternative`, `ComparisonResult`, `ValueEstimate`, `ConfidenceAssessment`.

### Step 1.4: Database & ORM Schema
* Create `natilah/models/database.py`:
  * Define SQLAlchemy declarative models corresponding to domain models: `NodeModel`, `GPUModel`, `JobModel`, `AllocationModel`, `TelemetrySampleModel`, `SchedulerDecisionModel`, `OpportunityModel`.
  * Add database indexes on `timestamp`, `job_id`, `gpu_id`, and `decision_id`.
  * Implement async engine initialization `init_db()` and session generator `get_db_session()`.

### Step 1.5: Read-Only Safety Guards
* Create `natilah/safety/guards.py`:
  * Implement `SafetyGuard` class that enforces `READ_ONLY` mode.
  * Explicitly intercept and reject any execution methods or mutation requests against production schedulers.

---

## Phase 2: Data Ingestion & Synthetic Data Engine

### Step 2.1: Abstract Ingestion Interface
* Create `natilah/ingestion/base.py`:
  * Abstract base class `DataSource` with `async ingest(db: AsyncSession)` and `validate()`.

### Step 2.2: Synthetic Data Generator with Injected Inefficiencies
* Create `natilah/ingestion/synthetic.py`:
  * Generate a 64-node cluster (8 GPUs per node; mixed A100-80GB and H100-80GB).
  * Generate 500 jobs over a 24-hour timeline with realistic submit, start, and end times.
  * Inject 5 specific inefficient decision patterns:
    1. **Over-Allocation Pattern**: Job requests 8 GPUs, but utilization metrics show only 4 GPUs active (>40% mean), while GPUs 5-8 stay <3%.
    2. **Poor Placement Pattern**: Multi-GPU job allocated across 2 nodes with 4 GPUs each when a single node with 8 idle GPUs was available.
    3. **Stranded GPU Fragmentation**: Single-GPU jobs placed on empty nodes, stranding 7 GPUs and breaking full 8-way NVLink cliques.
    4. **Idle Allocation Pattern**: Job holds 4 GPUs for 3 hours with <5% utilization (stalled input I/O or deadlock).
    5. **Queue Cascade Pattern**: A pending high-priority job delayed by 45 minutes because a lower-priority job over-allocated resources.

### Step 2.3: JSON Upload & Normalizer
* Create `natilah/ingestion/json_upload.py` and `natilah/ingestion/normalizer.py`:
  * Parse raw cluster events (JSON format) and convert raw metrics into normalized `Job`, `Allocation`, and `GPUUtilizationSample` domain models.

---

## Phase 3: Infrastructure State Reconstruction Engine

### Step 3.1: Point-In-Time Reconstructor
* Create `natilah/engine/state_reconstructor.py`:
  * Implement `ClusterStateReconstructor` class.
  * Query active allocations at timestamp $t$: $\text{start\_time} \le t < \text{end\_time}$.
  * Compute available node capacity, allocated GPUs, and idle GPUs at timestamp $t$.

### Step 3.2: Topology & Contiguity Mapping
* Implement `CapacityMap` calculations:
  * Detect available NVLink cliques on each node: 8-GPU full node, 4-GPU quad, 2-GPU pair.
  * Compute cluster-wide **Contiguity Index** ($\Phi_{\text{contig}}$) and **Largest Contiguous Block (LCB)**.

---

## Phase 4: Opportunity Detection Engine

### Step 4.1: Detector Registry
* Create `natilah/engine/opportunity_detector.py`:
  * Define `OpportunityDetector` abstract class.
  * Implement `DetectorRegistry` to run all active detectors against reconstructed cluster states.

### Step 4.2: Implement V1 Detectors
* Implement specific detectors:
  1. `OverAllocationDetector`: Identifies jobs where allocated GPUs $\ge 4$ but active utilized GPUs $\le 50\%$ for $>30$ minutes.
  2. `PlacementDetector`: Identifies multi-GPU jobs fragmented across nodes when single-node placement was feasible.
  3. `FragmentationDetector`: Identifies nodes with 1-2 idle GPUs while 8-GPU requests are queued.
  4. `IdleAllocationDetector`: Identifies allocations with GPU utilization $<5\%$ for $>15$ minutes.
  5. `QueueInefficiencyDetector`: Identifies queued jobs that could have started immediately under an alternative placement.

---

## Phase 5: Counterfactual Engine

### Step 5.1: Alternative Action Generation
* Create `natilah/engine/counterfactual.py`:
  * Define `CounterfactualEngine` class.
  * For each detected opportunity $X$, generate valid alternative decision $Y$.

### Step 5.2: Specific Counterfactual Generators
* Implement generators:
  1. `ReducedAllocationGenerator`: Proposes sizing job from $N$ GPUs down to $K$ GPUs (peak observed utilization $+ 20\%$ safety headroom).
  2. `BetterPlacementGenerator`: Re-runs Best-Fit Decreasing (BFD) bin packing on the reconstructed state to find non-fragmenting node placement.
  3. `ConsolidationGenerator`: Proposes consolidating sparse jobs onto single nodes to free complete 8-GPU nodes.
  4. `ReorderingGenerator`: Proposes backfilling or priority adjustments that unblock queued workloads.

### Step 5.3: Hard Constraint Validation
* Validate alternatives against strict operational rules:
  * GPU architecture compatibility (A100 vs H100 memory requirements).
  * VRAM capacity limit matching.
  * Single-node NVLink requirement for tensor-parallel workloads.
  * Discard any invalid alternative prior to comparison.

---

## Phase 6: Comparator, Value Calculator & Confidence Scorer

### Step 6.1: Metric Comparator (Simulation)
* Create `natilah/engine/comparator.py`:
  * Execute a lightweight discrete-event forward simulation for affected jobs under alternative $Y$.
  * Compute technical metric deltas: GPU-hours saved, utilization lift (%), idle GPU-hours recovered, queue time reduction, fragmentation score delta.

### Step 6.2: Value Calculator
* Create `natilah/engine/value_calculator.py`:
  * Support configurable economic parameters: `cost_per_gpu_hour` (A100: $2.21, H100: $3.49), amortization horizon, facility multiplier.
  * Compute financial metrics:
    $$\text{Compute Cost Avoided} = \text{GPU-Hours Saved} \times \text{Cost per GPU-Hour}$$
    $$\text{Equivalent GPUs Recovered} = \frac{\text{GPU-Hours Saved}}{\text{Analysis Hours}}$$
    $$\text{Monthly Value} = \text{Hourly Savings} \times 720$$
    $$\text{Annual Value} = \text{Monthly Value} \times 12$$
  * Explicitly return array of assumptions attached to every calculation.

### Step 6.3: Confidence & Explainability Scorer
* Create `natilah/engine/confidence.py`:
  * Compute composite confidence score (0.0 to 1.0) based on:
    * Data completeness (weight 0.20)
    * Utilization variance / signal strength (weight 0.25)
    * Constraint coverage (weight 0.20)
    * Alternative feasibility (weight 0.20)
    * Pattern recurrence (weight 0.15)
  * Assign confidence grade: HIGH ($\ge 0.75$), MEDIUM ($0.50 - 0.74$), LOW ($< 0.50$).
  * Generate plain-language rationale explaining why $Y$ outperforms $X$.

---

## Phase 7: Agent Layer & REST API

### Step 7.1: Infrastructure Agent Abstraction
* Create `natilah/agents/base_agent.py` and `natilah/agents/gpu_allocation_agent.py`:
  * Implement `GPUAllocationAgent` encapsulating the pipeline loop: Observe $X \to$ Reconstruct State $\to$ Detect Opportunity $\to$ Counterfactual $Y \to$ Compare $\to$ Calculate Value $\to$ Assign Confidence.

### Step 7.2: FastAPI Application & Endpoints
* Create `natilah/api/schemas.py` and `natilah/api/app.py`:
  * Implement endpoints:
    * `GET /api/dashboard/summary`: High-level metrics (GPUs analyzed, decisions analyzed, opportunities found, recoverable GPU capacity, monthly/annual value, production changes made = 0).
    * `GET /api/opportunities`: List of opportunities sorted by economic value.
    * `GET /api/opportunities/{id}`: Detailed view (What Happened X, Alternative Y, Technical Impact, Financial Value, Confidence & Rationale).
    * `POST /api/ingestion/generate`: Trigger synthetic dataset generation.
    * `POST /api/ingestion/upload`: Ingest custom JSON cluster dataset.
    * `POST /api/analysis/run`: Run intelligence analysis.
    * `GET /api/config/costs`: Retrieve or update economic cost models.

---

## Phase 8: Dashboard Frontend (Vanilla HTML/CSS/JS)

### Step 8.1: HTML Framework & Wireframe
* Create `dashboard/index.html`:
  * Build responsive layout with header, KPI metric banner, safety indicator ("Production changes made: 0"), opportunity feed, cost configuration drawer, and opportunity detail modal.

### Step 8.2: Styling System & Aesthetics
* Create `dashboard/css/styles.css`:
  * Implement dark-mode design system (`#0a0a0f` background, glassmorphism cards, `#3b82f6` electric blue highlights, `#10b981` green financial callouts).
  * Add micro-animations, hover transitions, dynamic modal overlays, and status pills.

### Step 8.3: Client Logic & Components
* Create `dashboard/js/api.js`, `dashboard/js/components.js`, `dashboard/js/charts.js`, `dashboard/js/app.js`:
  * Implement asynchronous API fetching, UI dynamic rendering, modal open/close interactions, and lightweight HTML Canvas timeline charts for GPU utilization comparisons.

---

## Phase 9: Testing, CLI Tools & End-to-End Verification

### Step 9.1: Standalone CLI Tooling
* Create `scripts/generate_demo_data.py`: CLI command to generate synthetic cluster database.
* Create `scripts/run_analysis.py`: CLI command to run Natilah analysis engine and output summary findings to terminal.

### Step 9.2: Comprehensive Test Suite
* Create tests under `tests/`:
  * `test_models.py`: Domain & ORM mapping integrity.
  * `test_ingestion.py`: Generator correctness & JSON validation.
  * `test_state_reconstructor.py`: Cluster state point-in-time snapshot accuracy.
  * `test_opportunity_detector.py`: Correct detection of all 5 injected inefficiency types.
  * `test_counterfactual.py`: Constraint validation & alternative generation.
  * `test_comparator.py` & `test_value_calculator.py`: Mathematical accuracy of deltas and economic projections.
  * `test_api.py`: FastAPI endpoint tests using `httpx`.
  * `test_end_to_end.py`: Complete pipeline integration test.

---

## Complete Verification Flow

1. Execute test suite: `pytest tests/ -v`
2. Run data generator script: `python scripts/generate_demo_data.py`
3. Run analysis engine script: `python scripts/run_analysis.py`
4. Launch FastAPI app server: `uvicorn natilah.api.app:app --port 8000`
5. Open browser at `http://localhost:8000/` and verify dashboard KPIs, opportunity feed, detail modals, and cost configuration edits.
