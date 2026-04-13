"""Phase B: LLM extraction → RequestSpec (Anthropic Opus or mock)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from staffing_agent.config_loader import load_decision_config, load_tier_classification_prompt
from staffing_agent.models.request_spec import RequestSpec

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)


def mock_llm_reason() -> str:
    """Why mock mode is active; empty string if live LLM should run."""
    if os.environ.get("STAFFING_AGENT_MOCK_LLM", "").strip() == "1":
        return "STAFFING_AGENT_MOCK_LLM=1"
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "ANTHROPIC_API_KEY is empty"
    return ""


def uses_mock_llm() -> bool:
    return bool(mock_llm_reason())


def _mock_spec() -> RequestSpec:
    th = load_decision_config()
    ver = th.get("spec_version", "?")
    return RequestSpec(
        tier=2,
        complexity_class="S",
        tier_rationale="Mock: default Tier 2 placeholder.",
        project_type_tags=[],
        summary=(
            f"Mock extraction (no Anthropic call). Decision-logic config v{ver}. "
            "Set ANTHROPIC_API_KEY and ensure STAFFING_AGENT_MOCK_LLM is not 1 for real Opus."
        ),
        confidence=0.0,
        notes="mock_llm",
    )


def extract_request_spec(thread_text: str, notion_excerpt: str = "") -> tuple[RequestSpec, str]:
    """
    Returns (RequestSpec, source) where source is 'mock' or 'anthropic'.
    """
    if uses_mock_llm():
        logger.warning("using mock LLM: %s", mock_llm_reason())
        return _mock_spec(), "mock"

    from staffing_agent.anthropic_llm import complete_json

    schema = RequestSpec.model_json_schema()
    th = load_decision_config()
    tc = load_tier_classification_prompt()
    rules = (tc.get("classification_rules") or "").strip()
    out_req = (tc.get("output_requirements") or "").strip()
    fw = (tc.get("framework_url") or "").strip()
    system = (
        "You are a staffing assistant implementing Node 1 (project classification) for Toloka Staffing Agent. "
        f"Decision-logic spec_version: {th.get('spec_version', 'unknown')}. "
        f"Project Classification Framework: {fw}\n\n"
        "### Tier & complexity rules (must follow)\n"
        f"{rules}\n\n"
        "### Output discipline\n"
        f"{out_req}\n\n"
        "Read the Slack thread and optional Notion excerpts. "
        "If tier is unclear, still extract any product signals (evals, languages, call, etc.); "
        "Node 3 lists people by role from Databricks when SQL is configured. "
        "Extract project type tags (short labels: e.g. Evals, TTS, multilingual). "
        "Output a single JSON object matching this JSON Schema (no markdown, no commentary):\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    user = (
        "### Slack thread\n"
        f"{thread_text}\n\n"
        "### Notion excerpts (may be empty)\n"
        f"{notion_excerpt or '(none)'}\n"
    )
    try:
        data = complete_json(system=system, user=user, max_tokens=2048)
        spec = RequestSpec.model_validate(data)
        return spec, "anthropic"
    except Exception as e:
        logger.exception("extraction failed: %s", e)
        return (
            RequestSpec(
                tier=None,
                summary="Extraction failed; see notes.",
                confidence=0.0,
                notes=str(e)[:500],
            ),
            "error",
        )
