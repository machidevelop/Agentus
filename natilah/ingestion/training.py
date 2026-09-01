"""Read-only training-run connector.

The scheduler knows a job held 8 GPUs for 40 hours. It does not know that the
run inside that job crashed twice and replayed itself from step 0 each time,
or that it spent a fifth of those hours waiting on its input pipeline. That
information only exists in the experiment tracker, which is why training
efficiency needs a connector of its own rather than another read of telemetry.

W&B and MLflow exports are the two shapes in the wild, so both are flattened
into one namespace and mapped onto `TrainingRun`. Nothing here writes: the
connector parses exports, and a live tracker would be read with list/get calls
only. No run is tagged, stopped, resumed, or deleted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from natilah.models.domain import ClusterDataset, ValidationIssue
from natilah.models.resources import TrainingRun

logger = logging.getLogger(__name__)

# Trackers name the same fact five ways; the alias lists are the whole mapping.
RUN_ID_KEYS = ("run_id", "id", "run_uuid", "run_name", "name")
JOB_ID_KEYS = ("job_id", "slurm_job_id", "k8s_job_id", "batch_job_id", "cluster_job_id")
SWEEP_ID_KEYS = ("sweep_id", "sweep", "experiment_id", "study_name", "hpo_id")
START_KEYS = ("start", "start_time", "created_at", "createdAt", "started_at")
END_KEYS = ("end", "end_time", "finished_at", "heartbeat_at", "heartbeatAt", "stopped_at")
STEP_KEYS = ("steps_completed", "_step", "global_step", "step", "steps")
RESTART_KEYS = ("restart_count", "restarts", "num_restarts", "retry_count", "attempt_count")
CHECKPOINT_KEYS = (
    "checkpoint_seconds",
    "checkpoint_time",
    "_checkpoint_seconds",
    "save_time_seconds",
    "ckpt_seconds",
)
STALL_KEYS = (
    "dataloader_stall_seconds",
    "dataloader_wait_seconds",
    "data_wait_seconds",
    "data_time_seconds",
    "input_stall_seconds",
)
GPU_COUNT_KEYS = ("gpu_count", "world_size", "num_gpus", "n_gpus", "gpus", "devices")
GPU_TYPE_KEYS = ("gpu_type", "gpu", "accelerator", "device_name", "gpu_model")
RESUME_KEYS = ("resumed_from_checkpoint", "resume", "resume_from", "restore_checkpoint", "resumed")
METRIC_NAME_KEYS = ("metric_name", "metric", "sweep_metric", "objective_metric", "target_metric")
EXIT_KEYS = ("exit_reason", "state", "status", "finish_reason", "termination_reason")

# Common objective names, tried in order when the export does not declare one.
FALLBACK_METRIC_NAMES = (
    "val_loss",
    "eval_loss",
    "validation_loss",
    "val_accuracy",
    "val_acc",
    "accuracy",
    "loss",
)

EXIT_REASON_MAP = {
    "finished": "completed",
    "completed": "completed",
    "complete": "completed",
    "success": "completed",
    "succeeded": "completed",
    "failed": "failed",
    "failure": "failed",
    "crashed": "failed",
    "error": "failed",
    "preempted": "preempted",
    "evicted": "preempted",
    "spot_reclaimed": "preempted",
    "requeued": "preempted",
    "killed": "killed",
    "cancelled": "killed",
    "canceled": "killed",
    "stopped": "killed",
    "diverged": "diverged",
    "nan": "diverged",
}

# A metric whose name says "lower is better" should not be read as a maximization
# objective just because the export forgot to say so.
MINIMIZED_METRIC_HINTS = ("loss", "err", "error", "perplexity", "ppl", "nll", "wer", "cer", "mse")

_TRUTHY_RESUME = {"true", "1", "yes", "must", "allow", "auto", "always", "latest"}
_FALSY_RESUME = {"false", "0", "no", "never", "none", "", "off"}


@dataclass
class TrainingTrackerConfig:
    """Where the runs come from and what to assume when the export is thin."""

    tracker: str = "wandb"  # wandb | mlflow | generic
    project: str = ""
    entity: str = ""
    export_path: str | None = None
    default_gpu_type: str = ""
    default_gpu_count: int = 1
    job_id_keys: Sequence[str] = field(default_factory=lambda: list(JOB_ID_KEYS))
    metric_name: str = ""
    higher_is_better: bool | None = None
    # Runs still going have no end time and no thrown-away work to price yet.
    skip_unfinished: bool = True


def _epoch_to_datetime(value: float) -> datetime:
    """MLflow stores milliseconds, most other exports store seconds."""
    seconds = value / 1000.0 if abs(value) > 1e11 else float(value)
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def parse_tracker_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_datetime(value)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                return _epoch_to_datetime(float(text))
            except ValueError:
                return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _flatten(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One scalar namespace per run, innermost values winning.

    W&B nests under `config`/`summary`, MLflow under `info`/`data.params`/
    `data.metrics`. Flattening once means every alias lookup is a dict get
    instead of a per-tracker branch.
    """
    flat: dict[str, Any] = {}

    def absorb(source: Any) -> None:
        if isinstance(source, Mapping):
            for key, value in source.items():
                if isinstance(value, Mapping) and "value" in value and len(value) <= 2:
                    flat[str(key)] = value["value"]  # W&B config entries
                elif not isinstance(value, (Mapping, list)):
                    flat[str(key)] = value
                elif isinstance(value, list):
                    flat[str(key)] = value

    absorb(raw)
    for key in ("info", "config", "summary", "summary_metrics", "params", "metrics", "tags"):
        absorb(raw.get(key))
    data = raw.get("data")
    if isinstance(data, Mapping):
        absorb(data)
        for key in ("params", "metrics", "tags"):
            absorb(data.get(key))
    wandb_block = raw.get("_wandb")
    if isinstance(wandb_block, Mapping):
        absorb(wandb_block)
    return flat


def _pick(flat: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in flat and flat[key] not in (None, ""):
            return flat[key]
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    number = _as_float(value)
    return default if number is None else int(number)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _FALSY_RESUME:
            return False
        if text in _TRUTHY_RESUME:
            return True
        return bool(text)  # a checkpoint path counts as resuming from one
    return False


def _sweep_goal(raw: Mapping[str, Any], flat: Mapping[str, Any]) -> tuple[str, bool | None]:
    """Metric name and direction, from a W&B sweep block or a flat goal key."""
    metric = raw.get("sweep_config") or raw.get("sweep") or {}
    if isinstance(metric, Mapping):
        block = metric.get("metric")
        if isinstance(block, Mapping):
            goal = str(block.get("goal", "")).lower()
            name = str(block.get("name", "") or "")
            if name:
                return name, (goal == "maximize") if goal else None
    goal = _pick(flat, ("metric_goal", "goal", "direction", "optimization_direction"))
    name = _pick(flat, METRIC_NAME_KEYS)
    if isinstance(name, Mapping):
        name = name.get("name", "")
    direction: bool | None = None
    if goal is not None:
        text = str(goal).lower()
        if text in ("maximize", "max", "higher_is_better", "asc"):
            direction = True
        elif text in ("minimize", "min", "lower_is_better", "desc"):
            direction = False
    return str(name or ""), direction


def _infer_direction(metric_name: str) -> bool:
    lowered = metric_name.lower()
    return not any(hint in lowered for hint in MINIMIZED_METRIC_HINTS)


class TrainingRunConnector:
    """Normalizes tracker exports into `TrainingRun`. Never writes anything."""

    read_only = True
    source = "training_tracker"

    def __init__(self, config: TrainingTrackerConfig | None = None):
        self.config = config or TrainingTrackerConfig()

    # ------------------------------------------------------------------ load

    def load_payload(self, payload: Any) -> list[TrainingRun]:
        """Runs from an already-parsed export: a list, or `{"runs": [...]}`."""
        runs: list[TrainingRun] = []
        for raw in self._raw_runs(payload):
            record = self.to_training_run(raw)
            if record is None:
                continue
            if self.config.skip_unfinished and record.end is None:
                continue
            runs.append(record)
        runs.sort(key=lambda r: (r.start, r.run_id))
        return runs

    def load_export(self, path: str | Path | None = None) -> list[TrainingRun]:
        """Runs from a JSON export on disk. Opened read-only."""
        target = Path(path or self.config.export_path or "")
        if not target.exists():
            raise FileNotFoundError(f"Training export not found: {target}")
        with target.open("r", encoding="utf-8") as handle:
            return self.load_payload(json.load(handle))

    def attach(self, dataset: ClusterDataset, runs: Sequence[TrainingRun]) -> ClusterDataset:
        """Put runs on a dataset in place. Nothing else about it is touched."""
        dataset.training_runs = list(runs)
        dataset.invalidate_indexes()
        return dataset

    # -------------------------------------------------------------- mapping

    def to_training_run(self, raw: Mapping[str, Any]) -> TrainingRun | None:
        flat = _flatten(raw)
        run_id = _pick(flat, RUN_ID_KEYS)
        if run_id is None:
            logger.debug("Skipping tracker record with no run id")
            return None

        start = parse_tracker_time(_pick(flat, START_KEYS))
        if start is None:
            logger.debug("Skipping run %s: no start time", run_id)
            return None
        end = parse_tracker_time(_pick(flat, END_KEYS))
        if end is not None and end < start:
            end = None

        metric_name, direction = _sweep_goal(raw, flat)
        metric_name = self.config.metric_name or metric_name
        if not metric_name:
            metric_name = next((m for m in FALLBACK_METRIC_NAMES if m in flat), "")
        if self.config.higher_is_better is not None:
            higher_is_better = self.config.higher_is_better
        elif direction is not None:
            higher_is_better = direction
        else:
            higher_is_better = _infer_direction(metric_name)

        best = _as_float(_pick(flat, (f"best_{metric_name}", f"{metric_name}_best", "best_metric")))
        final = _as_float(_pick(flat, (metric_name, f"final_{metric_name}", "final_metric")))
        if best is None:
            best = final
        if final is None:
            final = best

        gpu_count = _as_int(_pick(flat, GPU_COUNT_KEYS), self.config.default_gpu_count)
        gpu_type = _pick(flat, GPU_TYPE_KEYS) or self.config.default_gpu_type

        return TrainingRun(
            run_id=str(run_id),
            job_id=self._job_id(flat),
            sweep_id=self._optional_str(_pick(flat, SWEEP_ID_KEYS)),
            start=start,
            end=end,
            steps_completed=max(0, _as_int(_pick(flat, STEP_KEYS))),
            restart_count=max(0, _as_int(_pick(flat, RESTART_KEYS))),
            checkpoint_seconds=max(0.0, _as_float(_pick(flat, CHECKPOINT_KEYS)) or 0.0),
            dataloader_stall_seconds=max(0.0, _as_float(_pick(flat, STALL_KEYS)) or 0.0),
            gpu_count=max(1, gpu_count),
            gpu_type=str(gpu_type or ""),
            best_metric=best,
            final_metric=final,
            metric_name=metric_name,
            higher_is_better=higher_is_better,
            exit_reason=self._exit_reason(flat),
            resumed_from_checkpoint=_as_bool(_pick(flat, RESUME_KEYS)),
        )

    def _job_id(self, flat: Mapping[str, Any]) -> str | None:
        value = _pick(flat, tuple(self.config.job_id_keys))
        return self._optional_str(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, Mapping):
            value = value.get("id") or value.get("name")
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _exit_reason(flat: Mapping[str, Any]) -> str:
        raw = _pick(flat, EXIT_KEYS)
        if raw is None:
            return ""
        text = str(raw).strip().lower()
        return EXIT_REASON_MAP.get(text, "" if text in ("running", "active") else text)

    # ------------------------------------------------------------ validation

    def validate(self, payload: Any) -> list[ValidationIssue]:
        """Structural problems worth surfacing before anything is priced."""
        issues: list[ValidationIssue] = []
        raw_runs = self._raw_runs(payload)
        if not raw_runs:
            issues.append(ValidationIssue(field="runs", message="Export contains no training runs"))
        seen: set[str] = set()
        for index, raw in enumerate(raw_runs):
            flat = _flatten(raw)
            run_id = _pick(flat, RUN_ID_KEYS)
            label = str(run_id or f"#{index}")
            if run_id is None:
                issues.append(
                    ValidationIssue(field=f"runs[{index}].run_id", message="Run has no identifier")
                )
                continue
            if label in seen:
                issues.append(
                    ValidationIssue(field=f"runs[{index}].run_id", message=f"Duplicate run id {label}")
                )
            seen.add(label)
            if parse_tracker_time(_pick(flat, START_KEYS)) is None:
                issues.append(
                    ValidationIssue(field=f"runs[{index}].start", message=f"Run {label} has no start time")
                )
            record = self.to_training_run(raw)
            if record is None or record.end is None:
                continue
            wall_seconds = record.wall_hours * 3600.0
            accounted = record.checkpoint_seconds + record.dataloader_stall_seconds
            if wall_seconds > 0 and accounted > wall_seconds:
                issues.append(
                    ValidationIssue(
                        field=f"runs[{index}].timing",
                        message=(
                            f"Run {label} reports {accounted:,.0f}s of checkpoint+stall time "
                            f"inside a {wall_seconds:,.0f}s wall window"
                        ),
                    )
                )
            if not record.job_id:
                issues.append(
                    ValidationIssue(
                        field=f"runs[{index}].job_id",
                        message=f"Run {label} has no cluster job id; its GPUs cannot be resolved",
                    )
                )
        return issues

    @staticmethod
    def _raw_runs(payload: Any) -> list[Mapping[str, Any]]:
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            return [r for r in payload if isinstance(r, Mapping)]
        if isinstance(payload, Mapping):
            for key in ("runs", "training_runs", "experiments", "items", "data"):
                value = payload.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    return [r for r in value if isinstance(r, Mapping)]
        return []
