# Natilah — Current Situation
**Last updated: 2026-08-30**

---

## 1. What Natilah Is

Natilah is a read-only GPU infrastructure intelligence layer. It ingests cluster telemetry, reconstructs historical scheduler decisions, and generates counterfactual findings: "the scheduler did X, but Y was feasible and would have recovered N GPU-hours worth $M."

It does not replace the scheduler. It does not execute actions. It observes, measures waste, and produces confidence-scored findings with dollar values attached.

---

## 2. System Architecture

### 2.1 Pipeline (end to end)

```
[Data Source]
     │
     ▼
[Ingestion Connector]           slurm.py / kubernetes.py / alibaba_trace.py / json_upload.py
     │  normalizes to ClusterDataset
     ▼
[State Reconstructor]           state_reconstructor.py
     │  replays timeline, builds ClusterStateSnapshot per decision point
     ▼
[Opportunity Detectors]         opportunity_detector.py → DetectorRegistry
     │  4 detectors emit Observations (signals, not fixes)
     ▼
[Counterfactual Engine]         counterfactual.py + agents/tools.py
     │  agent calls read-only tools, proposes feasible alternative Y
     │  CounterfactualValidator checks hard constraints
     ▼
[Comparator]                    comparator.py
     │  computes MetricsDelta: GPU-hours saved, queue time reduction, etc.
     ▼
[Value Calculator]              value_calculator.py
     │  applies EconomicConfig (cost/GPU-hour, facility multiplier)
     │  produces ValueEstimate with monthly/annual projections
     ▼
[Confidence Scorer]             confidence.py
     │  scores 0–1 across constraint checks + uncertainty sources
     │  outputs ConfidenceLevel: high / medium / low
     ▼
[Finding]                       domain.py → Finding model
     │  persisted to SQLite via save_findings()
     ▼
[API / Dashboard]               api/ → dashboard/
```

### 2.2 Core Python modules

| Module | Purpose |
|---|---|
| `natilah/config.py` | Settings (DB URL, safety mode, GPU cost table, xAI/Grok config) |
| `natilah/models/domain.py` | All domain models: GPU, Node, Job, Allocation, Finding, etc. |
| `natilah/models/enums.py` | OpportunityType, ConfidenceLevel, JobState, SafetyMode |
| `natilah/engine/opportunity_detector.py` | 4 SignalDetectors: OverAllocation, IdleAllocation, QueueInefficiency, Fragmentation |
| `natilah/engine/state_reconstructor.py` | Replays job timeline → ClusterStateSnapshot at each decision point |
| `natilah/engine/counterfactual.py` | CounterfactualValidator: hard constraint checks on agent-proposed alternatives |
| `natilah/engine/comparator.py` | MetricsDelta computation between actual vs alternative |
| `natilah/engine/value_calculator.py` | GPU-hour → $ conversion with facility multiplier |
| `natilah/engine/confidence.py` | Multi-factor confidence scoring |
| `natilah/agents/gpu_allocation_agent.py` | V1 agent: orchestrates full pipeline per observation |
| `natilah/agents/tools.py` | Read-only probe tools the agent calls |
| `natilah/agents/llm.py` | Optional Grok integration (agent_mode: hybrid) |
| `natilah/ingestion/alibaba_trace.py` | Alibaba Open Cluster 2023 + V2026 trace connectors |
| `natilah/ingestion/slurm.py` | Read-only Slurm connector (squeue/sinfo/sacct) |
| `natilah/ingestion/kubernetes.py` | Read-only K8s connector (pod/node/metrics-server) |
| `natilah/api/` | FastAPI: ingestion, analysis, opportunities, dashboard routes |

### 2.3 Agent tools (read-only)

The `GPUAllocationAgent` calls these tools to explore the decision space:

| Tool | What it does |
|---|---|
| `inspect_utilization(dataset, job_id)` | Returns mean/peak GPU util per job, active vs idle GPU count |
| `list_idle_capacity(state, gpu_type, min_gpus)` | Returns NodeCapacity list sorted by idle GPU count |
| `probe_headroom_size(state, job)` | Checks if a job could fit in current idle capacity |
| `probe_release_idle_gpus(state, job)` | Simulates releasing idle GPUs from a running job |
| `probe_alternate_placement(state, job)` | Tests alternative node placements for a job |
| `probe_unblocked_queue(dataset, state, job)` | Checks which queued jobs would start if a blocker released GPUs |

### 2.4 Opportunity detector types

| Type | Detection logic |
|---|---|
| `idle_allocation` | Job allocated ≥4 GPUs, ran ≥30 min, mean GPU util <40% across majority of GPUs |
| `queue_inefficiency` | Job waited in queue while running jobs held idle GPUs that would have covered the request |
| `over_allocation` | Job allocated GPUs but zero showed mean util >40% (cluster-wide mean 0%) |
| `fragmentation` | Idle GPUs distributed across many nodes, no single node has a contiguous block ≥ requested size |

### 2.5 Confidence scoring

Each finding gets a `ConfidenceAssessment` (score 0–1):
- **High (≥0.8)**: All hard constraints pass, minimal uncertainty
- **Medium (0.6–0.8)**: Constraints pass but utilization data sparse or timing uncertain
- **Low (<0.6)**: Constraint violations or significant data gaps

Constraints checked per finding: `gpu_identity`, `node_identity`, `queued_job_exists`, `gpu_architecture_compatibility`, `gpu_count_matches_ids`.

### 2.6 Safety model

All operations run under `safety_mode = read_only`. The `SafetyGuard` rejects any `Action` where `is_read_only=False`. No scheduler commands are ever issued. The three modes defined (but only read_only active):
- `read_only` — observe and report only
- `propose` — generate recommendations (not wired)
- `execute_with_approval` — not implemented

### 2.7 Economic model

```python
GPU cost per hour (cloud reference):
  A100-80GB:  $2.21  (used in all validations so far)
  H100-80GB:  $3.49
  H200-141GB: $4.50
  B200-192GB: $5.80
  V100-32GB:  $1.10
  T4-16GB:    $0.35
  ... (16 GPU types in catalog)

Facility multiplier: 1.4x (recorded but NOT applied to headline figures)
Monthly hours assumed: 720
Value = (alternative_gpu_hours - actual_gpu_hours) × cost/hr × (720 / analysis_window_hours)
```

---

## 3. Validation Results

All tests run on **Alibaba Open Cluster Trace** data using `scripts/validate_alibaba.py`. Dataset: `data/alibaba_trace_2023/` + `data/alibaba_trace_2026/`. GPU type: A100-80GB throughout.

### 3.1 Validation run history

| Run file | Jobs | Analysis window | Findings | High conf | Avg conf | Util recovery | Queue recovery | Monthly value |
|---|---|---|---|---|---|---|---|---|
| `validation_500jobs.json` | 500 | ~10h | — | — | — | — | — | — |
| `validation_smoke_test.json` | ~100 | short | — | — | — | — | — | — |
| `validation_v2026_a100_5000.json` | 5,000 | 43.3h | 77 | 67 | 0.79 | 0.26% | — | $853 |
| `validation_v2026_a100_real_util.json` | 5,000 | 43.3h | 2,558 | 2,492 | 0.857 | **151%** ⚠️ | — | $1,014,175 |
| `validation_report.json` ✅ | 5,000 | 43.3h | 2,558 | 2,492 | 0.857 | 59.25% | 88.03% | **$535,185** |
| `validation_50k.json` ✅ | 50,000 | ~43h | 5,524 | 4,969 | 0.842 | 51.01% | 69.08% | **$203,503** |

**Key fix between runs**: `validation_v2026_a100_real_util` had inflated numbers (151% recovery — impossible) due to double-counting in deduplication. `validation_report` fixed dedup and split util vs queue metrics. These are the canonical results.

### 3.2 Canonical results — 5k jobs (validation_report.json)

```
Analysis window:    43.3 hours
GPU type:           A100-80GB @ $2.21/hr
Total findings:     2,558
High confidence:    2,492 (97.4%)
Avg confidence:     0.857

UTILIZATION
  Wasted GPU-hours (raw):     18,632h
  Recovered GPU-hours (dedup): 11,039h
  Recovery rate:              59.25%
  Monthly value:              $406,180

QUEUE
  Deduped wait-hours:         802.5h
  Recovery rate:              88.03%
  Monthly value:              $129,005

TOTAL MONTHLY VALUE:          $535,185
TOTAL ANNUAL VALUE:           ~$6.4M

Findings by type:
  idle_allocation:     2,088  (81.6%)
  queue_inefficiency:    269  (10.5%)
  over_allocation:       168   (6.6%)
  fragmentation:          33   (1.3%)
```

### 3.3 Scale test — 50k jobs (validation_50k.json)

```
Total findings:     5,524  (+116% vs 5k run)
High confidence:    4,969  (90.0%)
Avg confidence:     0.842  (-1.7% vs 5k)
Monthly value:      $203,503  (lower per-job density at scale — expected)
Util recovery:      51.01%
Queue recovery:     69.08%

Findings by type:
  idle_allocation:     4,540  (82.2%)
  queue_inefficiency:    394   (7.1%)
  fragmentation:         327   (5.9%)  ← 10× more than 5k run
  over_allocation:       263   (4.8%)

Key observation: Monthly value drops at 50k because larger sample includes
more "healthy" jobs that dilute waste density. Fragmentation jumps 10× because
more concurrent jobs compete for placement. Numbers going DOWN at scale is a
good sign — not hallucinating waste.
```

### 3.4 Top findings from validation_report.json (rank 1–7)

| Rank | Type | Job waited | Blocked by | Conf | Monthly $ | Verdict |
|---|---|---|---|---|---|---|
| 1 | queue_inefficiency | 1,397 min | 8-GPU idle job | 0.838 | $6,836 | LIKELY_VALID |
| 2 | queue_inefficiency | 1,051 min | 8-GPU idle job | 0.840 | $5,145 | LIKELY_VALID |
| 3 | queue_inefficiency | 947 min | 8-GPU idle job | 0.620 | $4,633 | REVIEW |
| 4 | queue_inefficiency | 774 min | 8-GPU idle job | 0.620 | $3,791 | REVIEW |
| 5 | queue_inefficiency | 774 min | 8-GPU idle job | 0.620 | $3,791 | REVIEW |
| 6 | queue_inefficiency | 720 min | 8-GPU idle job | 0.837 | $3,526 | LIKELY_VALID |
| 7 | queue_inefficiency | 688 min | 8-GPU idle job | 0.870 | $3,369 | LIKELY_VALID |

Verdict assignment: `LIKELY_VALID` = confidence ≥0.8, `REVIEW` = confidence 0.6–0.8.

---

## 4. Data Sources

### 4.1 Alibaba Open Cluster Trace (used for all tests)

- **2023 trace**: `data/alibaba_trace_2023/` — real GPU cluster workload from Alibaba production
- **2026 trace**: `data/alibaba_trace_2026/` — newer version with richer utilization signals
- Connector: `natilah/ingestion/alibaba_trace.py`
- Two configs: `OpenB2023Config` and `V2026Config` with different field mappings

### 4.2 Slurm connector (built, not yet used in production)

- `natilah/ingestion/slurm.py`
- Read-only: runs `squeue`, `sinfo`, `sacct` via SSH or local shell
- Normalizes to `ClusterDataset`
- Script: `scripts/ingest_slurm.py`

### 4.3 Kubernetes connector (built, not yet used in production)

- `natilah/ingestion/kubernetes.py`
- Read-only: uses `kubectl` / K8s API to read pods, nodes, metrics-server GPU metrics
- Normalizes to `ClusterDataset`
- Script: `scripts/ingest_kubernetes.py`

---

## 5. Dashboard

### 5.1 Stack

- **Framework**: Next.js 16 (App Router), React 19, TypeScript
- **UI**: shadcn/ui (`@shadcn/react`), Tailwind CSS v4
- **Charts**: Recharts 3.8 (BarChart, LineChart, AreaChart, ComposedChart, PieChart)
- **Tables**: TanStack Table v9
- **Forms/validation**: React Hook Form + Zod v4
- **State**: Zustand (sidebar/theme preferences)
- **Base template**: `arhamkhnz/next-shadcn-admin-dashboard` (adapted)
- **Location**: `M:\NATILAH\Agentus\dashboard\`

### 5.2 Pages

All 7 pages live at `/dashboard/<slug>`. Sidebar shows single "Intelligence" nav group.

#### `/dashboard/overview`
Base: Default template (metric-cards + ComposedChart + customer table)

Components:
- `metric-cards.tsx` — 4 KPI tiles: Monthly Recovery ($535k), Total Findings (2,558), GPU-Hours Recovered (11,039h), Queue Hours Saved (802.5h)
- `recovery-overview.tsx` — ComposedChart with Area + 2 Lines over 168 data points (3-month window): waste detected, recovered, queued. Period + segment selectors.
- `findings-summary.tsx` + `findings-summary-table/` — TanStack Table with 60 sample findings, filters: Type / Confidence / Detected date range / Sort

#### `/dashboard/findings`
Base: CRM template (kpi-cards + pipeline-activity + task-reminders + opportunities-table)

Components:
- `findings-kpi-cards.tsx` — 4 KPI cards with section heading, comparison lines vs previous run
- `waste-by-type.tsx` — Recharts BarChart with hatched SVG pattern, 12-month view, side panel (2,558 total), progress sub-card (queue findings vs target)
- `findings-timeline.tsx` — Two-column: waste distribution timeline bars + 42-bar monthly value goal visualization
- `findings-section.tsx` — Full TanStack Table: search + Type radio filter + Confidence radio filter + ellipsis pagination, 100 sample rows
- `findings-table/columns.tsx` — 8 columns: select, ID, type badge, confidence badge, 18-slot health strip, monthly value, verdict badge, actions

#### `/dashboard/cluster`
Base: CRM (KPI cards) + Infrastructure (environment grid)

Components:
- `cluster-kpi-cards.tsx` — 4 KPI section: Active GPUs (256), Idle GPUs (144), Avg Utilization (42.3%), Waste Identified ($535k)
- `node-activity.tsx` — Hatched BarChart, 24h of GPU-hours per hour, side panel (400 GPUs), peak window progress card (14:00–16:00, 71%)
- `gpu-status-grid.tsx` — 3 collapsible node groups × 8 GPUs each; per-GPU rows show status badge (Active/Idle/Over-allocated/Fragmented), utilization %, node ID, dropdown actions

#### `/dashboard/economics`
Base: Finance template (overview-kpis + income-breakdown + balance-distribution + transactions)

Components:
- `overview-kpis.tsx` — Bordered 2×2 KPI grid: Monthly Recovery, GPU-Hours Recovered, Queue Value, Confidence Rate
- `income-breakdown.tsx` — 3-column value sources with dashed vertical separators + color bars: Idle Allocation (82%, $438k), Queue (10%, $53k), Over-alloc+Frag (8%, $43k)
- `balance-distribution-card.tsx` — Donut chart (PieChart with inner radius), 4 segments totaling $535,185, GPU type selector dropdown
- `recovery-timeline.tsx` — LineChart: recovered vs waste baseline, weekly selector, 30 data points over 7 days
- `scheduled-analysis.tsx` — 3 upcoming analysis items (cluster re-scan, weekly report, manual review checkpoint) with Lucide icons

#### `/dashboard/trends`
Base: Analytics template (kpi-strip + toolbar + traffic-quality + realtime-visitors + top-pages + traffic-sources)

Components:
- `kpi-strip.tsx` — 5-across connected strip: Total Findings (5,524), High Confidence (4,969), Monthly Value (5k: $535k), Util Recovery (51.01%), Avg Confidence (0.842) — comparing 5k vs 50k runs
- `toolbar.tsx` — Run selector (5k/50k/all) + export dropdown
- `recovery-trend.tsx` — ComposedChart with 84 data points: recovered GPU-hours (solid) vs wasted GPU-hours (dashed), Week 1–4 x-axis
- `confidence-distribution.tsx` — 30-bar histogram of confidence scores, 4-stat grid (High: 4,969 / Medium: 500 / Avg: 0.842 / Total: 5,524)
- `top-findings.tsx` — Table: type / count / avg value / recovery % across finding types
- `run-comparison.tsx` — 3-tab horizontal bar chart: "5k Deduped" / "50k Run" / "By Type"

#### `/dashboard/gpu-health`
Base: Patient Monitoring template (full realtime waveform system)

Components: Full port of the patient monitoring system with domain rename:
- `page.tsx` — Full-bleed layout (data-content-padding=false), header bar (GPU count, date/time, telemetry icon), footer action buttons (Overview / GPU config / Alert review / Signal review / Trends / Print / Silence / Cluster telemetry badge)
- `gpu-monitoring.tsx` — Orchestrator: left panel = GPU card grid, right panel = selected GPU detail + tabs (Real time / Event log / Trends / Full history)
- `gpu-card.tsx` — Mini card per GPU: live ECG-style waveform + UTIL/MEM big numerics, alarm badge if triggered
- `gpu-detail.tsx` — 5 waveform trace rows (GPU Util / Mem Util / PCIe BW / Power / Temp) + 6 numeric vitals panel
- `gpu-trends.tsx` — 3 trend strip rows (utilization / memory / power) + recent events list
- `vital-waveform.tsx` — Recharts LineChart waveform renderer (lime=util, cyan=mem, amber=power, red=temp)
- `data.ts` — 10 GpuRecord objects, 2 with active alarms (idle N02-G1, overtemp N05-G0)
- Realtime system: `realtime-utils.ts`, `use-realtime-tick.ts`, `use-gpu-vital-series.ts`, `waveform-data.ts` — 100ms waveform tick, 1s trend tick, sliding signal windows from ECG/pleth/respiration templates

#### `/dashboard/review`
Base: Tasks template (full TanStack table + multi-filter toolbar)

Components:
- `reviews.tsx` — Full TanStack Table: row selection, column visibility toggle, multi-filter, sorting, pagination with rows-per-page + first/prev/next/last
- `columns.tsx` — 7 columns: select, FND-XXXX ID, description (sortable with action dropdown), type badge (sky/amber/purple/green), confidence badge with TrendingUp/Minus/TrendingDown icons, verdict badge, actions dropdown (Mark Valid / Mark Review / Mark Invalid / Copy ID / View Details)
- `data.ts` — Zod schema, 100 rows, type/confidence/verdict arrays with icons
- `reviews-toolbar.tsx` — Search input + TypeFilter + ConfidenceFilter dropdowns + reset button + column visibility toggle
- `type-filter.tsx` / `confidence-filter.tsx` — Multi-select checkbox dropdowns for type and confidence filters

### 5.3 Shell (unchanged from template)

- **Sidebar**: collapsible, cookie-persisted, single "Intelligence" nav group, Cpu icon + "Natilah" branding
- **Header**: sidebar toggle, search dialog, layout controls, theme switcher (light/dark + color presets), account switcher
- **Theme**: Zustand preferences store + SSR cookie boot script (no flash)
- **Auth pages**: `/auth/v1/login`, `/auth/v1/register`, `/auth/v2/login`, `/auth/v2/register` (template originals, not wired to backend yet)

### 5.4 Build status

```
✓ Compiled successfully
✓ TypeScript: 0 errors
✓ 17 routes generated
Dev server: http://localhost:3000
```

---

## 6. Next Steps (per validation plan)

Per the agreed validation-first rule: **no new features, agents, domains, or UI additions until validation passes**.

1. **Capture real data** — 7–30 days of real K8s or Slurm cluster telemetry using the built connectors
2. **Run full pipeline** on real data (not Alibaba synthetic trace)
3. **Manual review** — experienced engineer walks through top 20 findings, checks each against the Review Queue checklist:
   - Proposed Y was physically feasible at decision time
   - GPU type/count/topology constraints satisfied
   - No hidden affinity or locality constraint violated
   - Utilization data supports the waste claim
   - Value estimate is conservative (not inflated)
   - Alternative is operationally realistic
4. **Validation passes** if: ≥15/20 findings confirmed feasible by reviewer, avg confidence ≥0.8, no systematic hallucination pattern
5. **Only then**: decide on next product direction (API productization, customer pilots, etc.)

---

## 7. Repository

- **Repo**: `github.com/machidevelop/Agentus` (private), branch `main`
- **Git user**: `machimilah`
- **Stack**: Python 3.10+, FastAPI, SQLite (`aiosqlite`), Pydantic v2, Next.js 16
- **Last commits**:
  - `1a3ba4d` — Add read-only Kubernetes ingestion connector
  - `7887ca9` — Add read-only Slurm connector for real cluster data ingestion
  - `1abc047` — Initial commit: Natilah V1 MVP — read-only GPU infrastructure intelligence
- **Uncommitted changes**: `natilah/config.py`, `natilah/models/domain.py`, Alibaba ingestion code, all validation output files, dashboard/ directory
