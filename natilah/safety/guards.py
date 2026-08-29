"""Read-only enforcement. Natilah never mutates production infrastructure."""

from __future__ import annotations

from pydantic import BaseModel, Field

from natilah.config import settings
from natilah.models.enums import SafetyMode


class Action(BaseModel):
    name: str
    is_read_only: bool
    payload: dict = Field(default_factory=dict)


class SafetyViolation(Exception):
    def __init__(self, action_name: str, mode: SafetyMode):
        self.action_name = action_name
        self.mode = mode
        super().__init__(
            f"Action '{action_name}' is blocked in {mode.value} mode. "
            "Natilah is an observation and counterfactual intelligence layer; "
            "it does not modify infrastructure."
        )


class SafetyGuard:
    BLOCKED_ACTIONS = frozenset(
        {
            "modify_scheduler_config",
            "move_workload",
            "terminate_job",
            "allocate_gpu",
            "modify_kubernetes_resource",
            "execute_infrastructure_change",
            "preempt_job",
            "apply_placement",
            "reorder_queue",
            "resize_allocation",
        }
    )

    def __init__(self, mode: SafetyMode | str | None = None):
        raw = mode or settings.safety_mode
        self.mode = SafetyMode(raw) if not isinstance(raw, SafetyMode) else raw

    def check_action(self, action: Action) -> bool:
        if action.name in self.BLOCKED_ACTIONS:
            raise SafetyViolation(action.name, self.mode)
        if self.mode == SafetyMode.READ_ONLY and not action.is_read_only:
            raise SafetyViolation(action.name, self.mode)
        if self.mode == SafetyMode.PROPOSE and not action.is_read_only:
            raise SafetyViolation(action.name, self.mode)
        return True

    def assert_read_only(self) -> None:
        if self.mode != SafetyMode.READ_ONLY:
            return
        # V1 always stays read-only regardless of future mode interfaces.
        return
