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
    is_team_capacity_query,
    single_role_focus_from_thread,
    thread_has_availability_capacity_ping,
    thread_suggests_full_team_intent,
    thread_suggests_pre_sales_rfp_deal_shape,
)
from staffing_agent.models.request_spec import RequestSpec

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

LLM_ACTIONABLE_TIER_CONFIDENCE = 0.7

logger = logging.getLogger(__name__)
_EXPLICIT_TIER_IN_TEXT_RE = re.compile(r"(?i)\btier\s*([1-4])\b")
_STAFFING_CONTEXT_RE = re.compile(
    r"(?i)\b(need|staffing|staff|hire|soe|ssoe|sse|dpm|wfm|qm|owner|headcount|resourcing|"
    r"looking\s+for|who\s+can|join\s+us|open\s+role)\b"
)
_NARROW_CALL_SUPPORT_HINT = re.compile(
    r"(?i)\b("
    r"client\s+call|intro\s+call|discovery\s+call|join\s+(?:us\s+on\s+)?(?:the|a)\s+call|"
    r"on\s+the\s+call\s+with|call\s+with\s+(?:the\s+)?client|who\s+covers\s+the\s+call|"
    r"cover\s+the\s+call|call\s+support"
    r")\b"
)

_ATTIO_SPEC_STRING_FIELDS: tuple[str, ...] = (
    "request_type",
    "attio_deal_id",
    "attio_deal_name",
    "attio_company_name",
    "attio_deal_value",
    "attio_currency",
    "attio_stage",
    "attio_owner",
    "attio_source",
    "attio_expected_close",
    "attio_pipeline",
    "attio_territory",
    "attio_industry",
    "attio_notes",
    "attio_record_url",
    "attio_created_at",
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
    """Why non-live LLM path is active; empty string if Anthropic would run."""
    if intentional_mock_llm():
        return "STAFFING_AGENT_MOCK_LLM=1"
    if not anthropic_api_key_configured():
        return "ANTHROPIC_API_KEY is empty"
    return ""


def intentional_mock_llm() -> bool:
    return os.environ.get("STAFFING_AGENT_MOCK_LLM", "").strip() == "1"


def anthropic_api_key_configured() -> bool:
    return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())


def uses_mock_llm() -> bool:
    """True when extraction does not call Anthropic (intentional mock or missing API key)."""
    return intentional_mock_llm() or not anthropic_api_key_configured()


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
    allowed_narrow = ("pre_sales_shape", "call_support", "single_role")
    nss = out.get("narrow_staffing_scenario")
    if nss is None or (isinstance(nss, str) and not nss.strip()):
        out["narrow_staffing_scenario"] = None
    else:
        s = str(nss).strip()
        out["narrow_staffing_scenario"] = s if s in allowed_narrow else None
    pa = out.get("parsed_ask_summary_en")
    if pa is None:
        out["parsed_ask_summary_en"] = ""
    else:
        pa_s = str(pa).strip()
        out["parsed_ask_summary_en"] = pa_s[:1200] if len(pa_s) > 1200 else pa_s
    inc = out.get("include_full_team_candidates")
    if isinstance(inc, bool):
        out["include_full_team_candidates"] = inc
    elif inc is None:
        out["include_full_team_candidates"] = False
    else:
        out["include_full_team_candidates"] = str(inc).strip().lower() in ("1", "true", "yes", "y")
    ctags = out.get("call_support_role_tags")
    if ctags is None:
        out["call_support_role_tags"] = []
    elif isinstance(ctags, str):
        out["call_support_role_tags"] = [ctags.strip()] if ctags.strip() else []
    elif not isinstance(ctags, list):
        out["call_support_role_tags"] = []
    else:
        out["call_support_role_tags"] = [str(x).strip() for x in ctags if str(x).strip()]
    nsr = out.get("narrow_single_role")
    nsr_allowed = frozenset({"so", "soe", "dpm", "wfm", "qm", "se"})
    if nsr is None or (isinstance(nsr, str) and not str(nsr).strip()):
        out["narrow_single_role"] = None
    else:
        raw_nsr = str(nsr).strip().lower().replace(" ", "_").replace("-", "_")
        alias = {
            "ssoe": "soe",
            "ssoe+soe": "soe",
            "solution_engineer": "soe",
            "accountable_so": "so",
            "so_pool": "so",
        }
        raw_nsr = alias.get(raw_nsr, raw_nsr)
        out["narrow_single_role"] = raw_nsr if raw_nsr in nsr_allowed else None
    for ak in _ATTIO_SPEC_STRING_FIELDS:
        v = out.get(ak)
        if v is None:
            out[ak] = ""
        else:
            s = str(v).strip()
            out[ak] = s[:2000] if len(s) > 2000 else s
    return out


def apply_llm_tier_confidence_gate(spec: RequestSpec) -> RequestSpec:
    """Drop tier/complexity when Phase B confidence is below the actionable floor (CR-5)."""
    if spec.tier is None:
        return spec
    conf = float(spec.confidence or 0.0)
    if conf >= LLM_ACTIONABLE_TIER_CONFIDENCE:
        return spec
    extra = (
        f"Tier/complexity cleared: confidence {conf:.2f} < {LLM_ACTIONABLE_TIER_CONFIDENCE} "
        "(actionable tier requires confidence ≥ 0.7)."
    )
    notes = (spec.notes or "").strip()
    notes = f"{notes}\n{extra}".strip() if notes else extra
    return spec.model_copy(
        update={
            "tier": None,
            "complexity_class": None,
            "sese_path": False,
            "notes": notes[:2000],
        }
    )


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


def apply_narrow_staffing_thread_fallback(thread_text: str, spec: RequestSpec) -> RequestSpec:
    """
    When Phase B leaves ``narrow_staffing_scenario`` null, infer a narrow path from the Slack thread so
    routing matches product intent (single-role shortlist even when ``tier`` is set; call / RFP shapes).

    Does **not** override a non-null ``narrow_staffing_scenario`` from the LLM.

    Disable with ``STAFFING_NARROW_THREAD_FALLBACK=0``.
    """
    if (os.environ.get("STAFFING_NARROW_THREAD_FALLBACK") or "1").strip() == "0":
        return spec
    if spec.narrow_staffing_scenario is not None:
        return spec
    tp = thread_text or ""
    tl = tp.lower()

    _role_labels = {
        "so": "accountable SO",
        "soe": "SoE / SSoE",
        "dpm": "DPM",
        "wfm": "WFM",
        "qm": "QM",
        "se": "SE",
    }
    if not is_team_capacity_query(tp):
        role = single_role_focus_from_thread(tp)
        if role in _role_labels:
            if spec.tier is not None and thread_suggests_full_team_intent(tp):
                return spec
            pa0 = (spec.parsed_ask_summary_en or "").strip()
            if not pa0:
                pa0 = (
                    f"Narrow ask: {_role_labels[role]} shortlist "
                    "(auto-detected from thread — prefer explicit `narrow_staffing_scenario` from extraction)."
                )
            return spec.model_copy(
                update={
                    "narrow_staffing_scenario": "single_role",
                    "narrow_single_role": role,
                    "parsed_ask_summary_en": pa0[:1200],
                }
            )

    staffingish = (
        _thread_suggests_staffing_intent(tp)
        or is_likely_deal_notification_thread(tp)
        or spec.tier is not None
    )
    if staffingish and _NARROW_CALL_SUPPORT_HINT.search(tp):
        pa0 = (spec.parsed_ask_summary_en or "").strip()
        if not pa0:
            pa0 = (
                "Call / client intro — SO bench plus tagged SoE/DPM slices "
                "(auto-detected — prefer explicit `call_support_role_tags` from extraction)."
            )
        tags = [x for x in (spec.call_support_role_tags or []) if str(x).strip()]
        if not tags:
            tags = ["SSOE+SOE", "DPM"]
        return spec.model_copy(
            update={
                "narrow_staffing_scenario": "call_support",
                "call_support_role_tags": tags,
                "parsed_ask_summary_en": pa0[:1200],
            }
        )

    if thread_suggests_pre_sales_rfp_deal_shape(tp) and (
        is_likely_deal_notification_thread(tp)
        or "deal value" in tl
        or spec.tier is not None
        or _thread_suggests_staffing_intent(tp)
        or thread_has_availability_capacity_ping(tp)
    ):
        pa0 = (spec.parsed_ask_summary_en or "").strip()
        if not pa0:
            pa0 = (
                "Pre-sales / RFP scoping — SO bench first "
                "(auto-detected — prefer explicit `pre_sales_shape` from extraction)."
            )
        return spec.model_copy(
            update={
                "narrow_staffing_scenario": "pre_sales_shape",
                "parsed_ask_summary_en": pa0[:1200],
            }
        )

    return spec


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


def _intentional_mock_spec(thread_text: str) -> RequestSpec:
    th = load_decision_config()
    ver = th.get("spec_version", "?")
    brief = _thread_brief_for_fallback(thread_text)
    clip = brief[:240] + ("…" if len(brief) > 240 else "")
    return RequestSpec(
        thread_kind="unclear",
        tier=None,
        complexity_class=None,
        tier_rationale="",
        project_type_tags=[],
        judge="",
        summary=f"Mock mode (STAFFING_AGENT_MOCK_LLM=1); decision-logic v{ver}. Preview: {clip}",
        confidence=0.0,
        notes="mock_llm",
    )


def _llm_unavailable_spec(thread_text: str) -> RequestSpec:
    brief = _thread_brief_for_fallback(thread_text)
    tk = "deal_notification" if is_likely_deal_notification_thread(thread_text) else "unclear"
    return RequestSpec(
        thread_kind=tk,
        tier=None,
        complexity_class=None,
        tier_rationale="",
        project_type_tags=[],
        judge="",
        summary=brief,
        confidence=0.0,
        notes="Classification unavailable: ANTHROPIC_API_KEY is not set. Heuristic routing only.",
    )


def extract_request_spec(thread_text: str, notion_excerpt: str = "") -> tuple[RequestSpec, str]:
    """
    Returns (RequestSpec, source).

    ``source`` is one of: ``anthropic``, ``mock`` (``STAFFING_AGENT_MOCK_LLM=1``),
    ``llm_unavailable`` (no API key), ``anthropic_fallback``, ``anthropic_rescue``, ``error``.

    `notion_excerpt` may include Notion + Google Docs text (same field as before; name kept for compatibility).
    """
    if intentional_mock_llm():
        logger.warning("STAFFING_AGENT_MOCK_LLM=1 (intentional mock; no Opus call)")
        spec = _intentional_mock_spec(thread_text)
        spec = apply_narrow_staffing_thread_fallback(thread_text, spec)
        return apply_forced_tier(spec), "mock"
    if not anthropic_api_key_configured():
        logger.warning("Anthropic unavailable: ANTHROPIC_API_KEY empty")
        spec = _llm_unavailable_spec(thread_text)
        spec = apply_narrow_staffing_thread_fallback(thread_text, spec)
        return apply_forced_tier(spec), "llm_unavailable"

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
        "Deal + availability/capacity wording on a shaped thread should yield a tier **only** when you can justify "
        "it (six dimensions, anti-size) with **confidence ≥ 0.7**; otherwise keep tier null. "
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
        spec = apply_llm_tier_confidence_gate(spec)
        spec = apply_narrow_staffing_thread_fallback(thread_text, spec)
        return apply_forced_tier(spec), "anthropic"
    except Exception as e:
        logger.exception("extraction failed: %s", e)
        if is_likely_deal_notification_thread(thread_text):
            logger.warning("using deal-feed RequestSpec fallback after Phase B failure")
            fb = _deal_feed_fallback_spec(thread_text, e)
            fb = apply_narrow_staffing_thread_fallback(thread_text, fb)
            return apply_forced_tier(fb), "anthropic_fallback"
        rescue = _extraction_rescue_spec(thread_text, e)
        if rescue is not None:
            logger.warning("using staffing rescue RequestSpec after Phase B failure (explicit tier in thread)")
            rescue = apply_narrow_staffing_thread_fallback(thread_text, rescue)
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
