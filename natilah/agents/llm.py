"""Optional SpaceXAI (xAI) client for agent reasoning. Server-side only."""

from __future__ import annotations

import json
import logging
from typing import Any

from natilah.config import settings

logger = logging.getLogger(__name__)

SYSTEM = """You are a Natilah infrastructure intelligence agent.
You do not schedule, pack, or modify infrastructure.
You observe an actual historical decision X and reconstructed cluster context.
Identify credible alternative decisions Y that were operationally feasible at that moment.
Do not assume bin-packing, GPU downsizing, consolidation, or queue reordering are correct.
Only propose Y when the evidence supports feasibility. Return [] if none are credible.
Never instruct anyone to apply the alternative in production."""


def llm_available() -> bool:
    return bool(settings.xai_api_key)


def propose_with_grok(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    if not llm_available():
        return []
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; skipping Grok proposal")
        return []

    client = OpenAI(api_key=settings.xai_api_key, base_url=settings.xai_base_url)
    user = (
        "Evidence pack (JSON). Propose zero or more alternatives.\n"
        "Return JSON only: {\"alternatives\": [{\"description\": str, \"proposed_action\": object, "
        "\"rationale\": str, \"tools_requested\": [str]}]}\n\n"
        + json.dumps(evidence, default=str)[:12000]
    )
    try:
        response = client.responses.create(
            model=settings.xai_model,
            input=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        text = getattr(response, "output_text", None) or ""
        if not text:
            return []
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            return []
        payload = json.loads(text[start : end + 1])
        alts = payload.get("alternatives") or []
        return [a for a in alts if isinstance(a, dict)]
    except Exception:
        logger.exception("Grok proposal failed; continuing with tool-synthesized candidates")
        return []
