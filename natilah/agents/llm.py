"""Optional xAI (Grok) reasoning for the specialized agents. Server-side only.

The model's job is bounded on purpose:

* investigate  — choose which read-only tools to run next
* reason       — read the evidence those tools returned
* propose      — draft candidate alternatives Y in a fixed schema

The model never simulates the cluster, never scores value, never decides
feasibility, and never sees an execution path. Every candidate it returns is
re-validated deterministically against reconstructed state, and anything that
references a GPU, node, or job that did not exist at that moment is rejected.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from natilah.config import settings

logger = logging.getLogger(__name__)

SYSTEM = """You are an investigation component inside Natilah, a read-only GPU
infrastructure intelligence system. You are given the decision an existing
scheduler actually made (X) and evidence collected by deterministic read-only
tools from reconstructed cluster state.

Your job is to identify credible alternative decisions (Y) that were
operationally feasible at that exact moment.

Hard rules:
- Use only facts present in the evidence. Never invent GPUs, nodes, jobs,
  utilization numbers, topology, or scheduler behaviour.
- Only reference gpu_ids, node_ids and job_ids that appear in the evidence.
- Do not assume bin-packing, downsizing, consolidation, preemption or queue
  reordering is inherently correct. Each must be justified by the evidence.
- Do not estimate savings, cost, or confidence. Another component does that.
- Return [] when the evidence does not support any credible alternative.
- Never instruct anyone to apply a change in production."""

INVESTIGATE_SYSTEM = """You are an investigation planner inside Natilah, a
read-only GPU infrastructure intelligence system. Given an observed scheduler
decision and partial evidence, choose which read-only tools to run next to
decide whether a better decision was feasible. Choose only tools from the
catalog. Prefer tools that could falsify the hypothesis. Return [] when the
evidence already answers the question."""


def llm_available() -> bool:
    return bool(settings.xai_api_key)


def _client():
    from openai import OpenAI

    return OpenAI(api_key=settings.xai_api_key, base_url=settings.xai_base_url)


def _complete(system: str, user: str) -> dict[str, Any] | None:
    if not llm_available():
        return None
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        logger.warning("openai package not installed; LLM investigation disabled")
        return None
    try:
        response = _client().responses.create(
            model=settings.xai_model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = getattr(response, "output_text", None) or ""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        return json.loads(text[start : end + 1])
    except Exception:
        logger.exception("LLM call failed; continuing with deterministic candidates only")
        return None


def plan_investigation(
    objective: str,
    evidence: dict[str, Any],
    catalog: list[dict[str, Any]],
    max_calls: int = 4,
) -> list[dict[str, Any]]:
    """Ask the model which read-only tools to run next. Returns tool requests."""
    user = (
        f"Objective: {objective}\n"
        f"Tool catalog (JSON): {json.dumps(catalog)}\n"
        f"Evidence so far (JSON): {json.dumps(evidence, default=str)[:10000]}\n\n"
        "Return JSON only: {\"tool_calls\": [{\"tool\": str, \"args\": object}]}. "
        f"At most {max_calls} calls."
    )
    payload = _complete(INVESTIGATE_SYSTEM, user)
    if not payload:
        return []
    calls = payload.get("tool_calls") or []
    out: list[dict[str, Any]] = []
    for call in calls[:max_calls]:
        if isinstance(call, dict) and isinstance(call.get("tool"), str):
            args = call.get("args")
            out.append({"tool": call["tool"], "args": args if isinstance(args, dict) else {}})
    return out


def propose_alternatives(objective: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Ask the model for candidate alternatives Y. Schema-bound, never trusted."""
    user = (
        f"Objective: {objective}\n"
        "Evidence pack (JSON) describing the observed decision X and the cluster state "
        "around it.\n"
        "Return JSON only: {\"alternatives\": [{\"description\": str, \"proposed_action\": "
        "{\"kind\": \"resize\"|\"place\"|\"release_gpus\"|\"reorder\"|\"consolidate\", "
        "\"gpu_count\": int, \"gpu_ids\": [str], \"node_ids\": [str], ...}, "
        "\"rationale\": str, \"evidence_refs\": [str]}]}\n\n"
        + json.dumps(evidence, default=str)[:12000]
    )
    payload = _complete(SYSTEM, user)
    if not payload:
        return []
    alts = payload.get("alternatives") or []
    return [a for a in alts if isinstance(a, dict) and a.get("proposed_action")]


# Back-compat with the V1 single-agent entry point.
def propose_with_grok(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return propose_alternatives("gpu_allocation", evidence)
