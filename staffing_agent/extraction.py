"""Phase B: LLM extraction → RequestSpec (Anthropic Opus or mock)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from staffing_agent.config_loader import load_decision_config, load_tier_classification_prompt
from staffing_agent.intent import (
    is_likely_deal_notification_thread,
    thread_has_availability_capacity_ping,
)
from staffing_agent.models.request_spec import RequestSpec

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

_EXPLICIT_TIER_IN_TEXT_RE = re.compile(r"(?i)\btier\s*([1-4])\b")
_STAFFING_CONTEXT_RE = re.compile(
    r"(?i)\b(need|staffing|staff|hire|soe|ssoe|sse|dpm|wfm|qm|owner|headcount|resourcing|"
    r"looking\s+for|who\s+can|join\s+us|open\s+role)\b"
)


def explicit_tier_in_thread(thread_text: str) -> int | None:
    """First explicit ``tier 1`` … ``tier 4`` (case-insensitive) in the thread."""
    m = _EXPLICIT_TIER_IN_TEXT_RE.search(thread_text or "")
    return int(m.group(1)) if m else None


def _thread_suggests_staffing_intent(thread_text: str) -> bool:
    if _STAFFING_CONTEXT_RE.search(thread_text or ""):
        return True
    return thread_has_availability_capacity_ping(thread_text or "")


def _coerce_tier_value(val: Any) -> int | None:
    """Map LLM junk (``Tier 3`` string, float, out-of-range int) to 1..4 or None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if 1 <= val <= 4 else None
    if isinstance(val, float):
        if val != int(val):
            return None
        n = int(val)
        return n if 1 <= n <= 4 else None
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            n = int(s)
            return n if 1 <= n <= 4 else None
        m = re.search(r"(?i)\btier\s*([1-4])\b", s)
        if m:
            return int(m.group(1))
    return None


def _extraction_rescue_spec(thread_text: str, exc: BaseException) -> RequestSpec | None:
    """
    When Phase B throws (API/JSON/validation), recover a usable spec if the user already typed
    ``tier N`` in a staffing-shaped message — avoids “Extraction failed” + empty tier.
    """
    tier_g = explicit_tier_in_thread(thread_text)
    if tier_g is None:
        return None
    if not _thread_suggests_staffing_intent(thread_text):
        return None
    brief = _thread_brief_for_fallback(thread_text)
    cc = "M" if tier_g >= 3 else "S"
    tags: list[str] = []
    if re.search(r"(?i)\bcoding\b", thread_text or ""):
        tags.append("Coding")
    err = f"Phase B error ({type(exc).__name__}): {str(exc)[:280]}"
    return RequestSpec(
        thread_kind="staffing_request",
        tier=tier_g,
        complexity_class=cc,
        tier_rationale=(
            f"Heuristic rescue: explicit Tier {tier_g} in thread after Phase B failure; "
            "confirm when extraction is healthy."
        ),
        project_type_tags=tags,
        summary=brief,
        confidence=0.55,
        notes=(
            f"{err}. Tier and complexity were recovered from thread text (not from LLM JSON). "
            "Check Anthropic/LiteLLM logs if this happens often."
        )[:2000],
    )


def mock_llm_reason() -> str:
    """Why mock mode is active; empty string if live LLM should run."""
    if os.environ.get("STAFFING_AGENT_MOCK_LLM", "").strip() == "1":
        return "STAFFING_AGENT_MOCK_LLM=1"
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "ANTHROPIC_API_KEY is empty"
    return ""


def uses_mock_llm() -> bool:
    return bool(mock_llm_reason())


def forced_tier_from_env() -> int | None:
    """
    Optional override for Phase B: set ``STAFFING_FORCE_TIER`` to ``1``–``4`` to always use that tier
    for Node 2–3 (e.g. force Tier 3 team layout + project_staffing snapshot) regardless of LLM output.
    """
    raw = (os.environ.get("STAFFING_FORCE_TIER") or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        logger.warning("STAFFING_FORCE_TIER ignored (not an integer): %r", raw)
        return None
    if 1 <= v <= 4:
        return v
    logger.warning("STAFFING_FORCE_TIER ignored (must be 1–4): %r", raw)
    return None


def _thread_brief_for_fallback(thread_text: str, max_chars: int = 480) -> str:
    """One-line preview when LLM output cannot be parsed (deal-feed fallback)."""
    t = (thread_text or "").replace("\r", "\n")
    lines: list[str] = []
    for line in t.split("\n"):
        line = re.sub(r"^<@[^>]+>:\s*", "", line.strip())
        if line and not line.startswith("_[no extractable text"):
            lines.append(line)
    out = " ".join(lines)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out or "CRM / deal thread (no extractable preview)."


def _normalize_llm_spec_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Best-effort coercion so minor model mistakes still validate."""
    out = dict(data)
    tk = out.get("thread_kind")
    if tk is not None and tk not in (
        "deal_notification",
        "staffing_request",
        "capacity_question",
        "unclear",
    ):
        out["thread_kind"] = None
    out["tier"] = _coerce_tier_value(out.get("tier"))
    conf = out.get("confidence")
    if isinstance(conf, str):
        try:
            conf = float(conf)
        except ValueError:
            conf = 0.0
    if isinstance(conf, (int, float)):
        out["confidence"] = max(0.0, min(1.0, float(conf)))
    cc = out.get("complexity_class")
    if isinstance(cc, str):
        cc = cc.strip().upper()[:1]
        if cc in ("S", "M", "L"):
            out["complexity_class"] = cc
        else:
            out["complexity_class"] = None
    elif cc is not None and cc not in ("S", "M", "L"):
        out["complexity_class"] = None
    tags = out.get("project_type_tags")
    if tags is None:
        pass
    elif isinstance(tags, str):
        out["project_type_tags"] = [tags.strip()] if tags.strip() else []
    elif not isinstance(tags, list):
        out["project_type_tags"] = []
    else:
        out["project_type_tags"] = [str(x).strip() for x in tags if str(x).strip()]
    j = out.get("judge")
    if isinstance(j, str):
        j = j.strip()
        if len(j) > 80:
            j = j[:77] + "…"
        out["judge"] = j
    elif j is None:
        out["judge"] = ""
    else:
        out["judge"] = str(j).strip()[:80]
    sp = out.get("sese_path")
    if isinstance(sp, bool):
        out["sese_path"] = sp
    elif sp is None:
        out["sese_path"] = False
    else:
        out["sese_path"] = str(sp).strip().lower() in ("1", "true", "yes", "y")
    return out


def _deal_feed_fallback_spec(thread_text: str, exc: BaseException) -> RequestSpec:
    """When Phase B fails but the thread looks like Attio/CRM — avoid generic 'unclear'."""
    brief = _thread_brief_for_fallback(thread_text)
    err_note = f"Heuristic fallback (Phase B error: {type(exc).__name__}: {str(exc)[:350]})"
    return RequestSpec(
        thread_kind="deal_notification",
        tier=None,
        complexity_class=None,
        tier_rationale="",
        project_type_tags=[],
        summary=brief,
        confidence=0.35,
        notes=err_note[:2000],
    )


def apply_deal_feed_availability_tier_hint(thread_text: str, spec: RequestSpec) -> RequestSpec:
    """
    When Phase B leaves ``tier`` null but the thread is a deal/CRM feed **and** includes an availability
    ping (``who_is_available``, “who is available”, “team capacity”, …), set a **hypothesis** Tier 3 · M
    so Node 2–3 can run. Disable with ``STAFFING_DEAL_AVAILABILITY_TIER_HINT=0``.
    """
    if spec.tier is not None:
        return spec
    if (os.environ.get("STAFFING_DEAL_AVAILABILITY_TIER_HINT") or "1").strip() == "0":
        return spec
    if not is_likely_deal_notification_thread(thread_text):
        return spec
    if not thread_has_availability_capacity_ping(thread_text):
        return spec
    rationale = (spec.tier_rationale or "").strip()
    tag = (
        "[Deal feed + availability ping: hypothesis Tier 3 · M so Node 2–3 can run; "
        "confirm or adjust with Delivery.]"
    )
    rationale = f"{rationale}\n{tag}".strip() if rationale else tag
    notes = (spec.notes or "").strip()
    nextra = "Auto-tier hint: CRM/deal thread + availability / who_is_available wording."
    notes = f"{notes}\n{nextra}".strip() if notes else nextra
    return spec.model_copy(
        update={
            "tier": 3,
            "complexity_class": "M",
            "tier_rationale": rationale[:8000],
            "notes": notes[:2000],
            "confidence": max(float(spec.confidence or 0), 0.42),
        }
    )


def apply_forced_tier(spec: RequestSpec) -> RequestSpec:
    ft = forced_tier_from_env()
    if ft is None:
        return spec
    prev = spec.tier
    tr = (spec.tier_rationale or "").strip()
    if tr:
        tr = f"{tr}\n_STAFFING_FORCE_TIER={ft} (was tier {prev!r})_"
    else:
        tr = f"_STAFFING_FORCE_TIER={ft} (was tier {prev!r})_"
    notes = (spec.notes or "").strip()
    if prev != ft:
        extra = f"tier overridden {prev!r} → {ft}"
        notes = f"{notes}; {extra}" if notes else extra
    # Tier 3 ownership row uses complexity M — align when forcing tier 3.
    cc = "M" if ft == 3 else spec.complexity_class
    logger.info("STAFFING_FORCE_TIER: applying tier %s (previous %s)", ft, prev)
    return spec.model_copy(
        update={
            "tier": ft,
            "complexity_class": cc,
            "tier_rationale": tr,
            "notes": notes[:2000],
        }
    )


def _mock_spec() -> RequestSpec:
    th = load_decision_config()
    ver = th.get("spec_version", "?")
    return RequestSpec(
        thread_kind="unclear",
        tier=2,
        complexity_class="S",
        tier_rationale="Mock: default Tier 2 placeholder.",
        project_type_tags=[],
        judge="Microsoft Copilot QA validation · 948 turns · hard May 22",
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

    `notion_excerpt` may include Notion + Google Docs text (same field as before; name kept for compatibility).
    """
    if uses_mock_llm():
        logger.warning("using mock LLM: %s", mock_llm_reason())
        return apply_forced_tier(_mock_spec()), "mock"

    from staffing_agent.anthropic_llm import complete_json

    schema = RequestSpec.model_json_schema()
    th = load_decision_config()
    tc = load_tier_classification_prompt()
    rules = (tc.get("classification_rules") or "").strip()
    fa = (tc.get("framework_alignment") or "").strip()
    out_req = (tc.get("output_requirements") or "").strip()
    fw = (tc.get("framework_url") or "").strip()
    boundary = (tc.get("system_boundary") or "").strip()
    boundary_block = f"### System boundary (enforced)\n{boundary}\n\n" if boundary else ""
    fa_block = f"{fa}\n\n" if fa else ""

    system = (
        "You are a staffing assistant implementing Node 1 (project classification) for Toloka Staffing Agent. "
        f"Decision-logic spec_version: {th.get('spec_version', 'unknown')}. "
        f"Project Classification Framework (canonical reference): {fw}\n\n"
        "### Tier & complexity rules (must follow)\n"
        f"{rules}\n\n"
        f"{fa_block}"
        "When the thread describes an RL-gym / multi-app pilot with domain-heavy delivery and a scale path, "
        "use **Tier 3** and complexity **M**, not Tier 2 — unless the scope is clearly a simple standard pipeline only.\n\n"
        "### Output discipline\n"
        f"{out_req}\n\n"
        f"{boundary_block}"
        "Read the Slack thread and optional Notion excerpts. "
        "If the thread is pasted proposal copy, FAQ, or 'better phrasing' without any staffing or availability signal, "
        "set tier to null — do not assign Tier 1–4 from product description alone. "
        "**Exception:** if the thread combines a CRM/Attio/new-deal context with @who_is_available or "
        "'who is available' / 'team capacity' / Russian equivalents, you MUST assign hypothesis tier 1–4 and "
        "complexity_class — that is a Delivery capacity question on a shaped deal, not FYI-only. "
        "When tier is set and unclear, still extract product signals (evals, languages, call, etc.); "
        "Node 3 lists people by role from Databricks when SQL is configured. "
        "Extract project type tags when they help staffing (short labels: e.g. Evals, TTS, multilingual); "
        "tags are for internal skill matching — do not paste tag lists into `judge`. "
        "Generate a single `judge` line, max 80 characters, format: `<client> <project_type> · <key_signal>`. Examples: "
        "`Microsoft Copilot QA validation · 948 turns · hard May 22`; "
        "`Shopify Sidekick eval · agentic · 6-week pilot`; "
        "`Amazon Lab126 video collection · multimodal · ramping`. "
        "Do NOT put Situation/Complication/Answer prose in `judge`. Do NOT explain what Tier N means in `judge`. "
        "Put SCQA-style reasoning only in `tier_rationale` / `notes` (not shown in slim Slack). "
        "Set `sese_path` true only when the thread clearly describes the Tier 2 SeSe external-projects lean staffing path; "
        "otherwise false. "
        "when tier is null, omit or minimize tags. "
        "Output a single JSON object matching this JSON Schema (no markdown, no commentary):\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    user = (
        "### Slack thread\n"
        f"{thread_text}\n\n"
        "### Linked pages (Notion + Google Docs; may be empty)\n"
        f"{notion_excerpt or '(none)'}\n"
    )
    try:
        data = complete_json(system=system, user=user, max_tokens=4096)
        data = _normalize_llm_spec_dict(data)
        spec = RequestSpec.model_validate(data)
        spec = apply_deal_feed_availability_tier_hint(thread_text, spec)
        return apply_forced_tier(spec), "anthropic"
    except Exception as e:
        logger.exception("extraction failed: %s", e)
        if is_likely_deal_notification_thread(thread_text):
            logger.warning("using deal-feed RequestSpec fallback after Phase B failure")
            fb = _deal_feed_fallback_spec(thread_text, e)
            fb = apply_deal_feed_availability_tier_hint(thread_text, fb)
            return apply_forced_tier(fb), "anthropic_fallback"
        rescue = _extraction_rescue_spec(thread_text, e)
        if rescue is not None:
            logger.warning("using staffing rescue RequestSpec after Phase B failure (explicit tier in thread)")
            rescue = apply_deal_feed_availability_tier_hint(thread_text, rescue)
            return apply_forced_tier(rescue), "anthropic_rescue"
        return (
            apply_forced_tier(
                RequestSpec(
                    thread_kind="unclear",
                    tier=None,
                    summary="Extraction failed; see notes.",
                    confidence=0.0,
                    notes=str(e)[:500],
                )
            ),
            "error",
        )
