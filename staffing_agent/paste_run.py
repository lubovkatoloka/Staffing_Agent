"""CLI: run Phase A + B + C on pasted thread text (same logic as @mention, without Socket Mode)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from staffing_agent.extraction import extract_request_spec
from staffing_agent.intent import (
    is_team_capacity_query,
    multi_roles_from_thread,
    only_role_from_thread,
    single_role_focus_from_thread,
    thread_suggests_full_team_intent,
    thread_suggests_pre_sales_rfp_deal_shape,
)
from staffing_agent.decision.node2_rules import node2_slack_markdown
from staffing_agent.models.request_spec import RequestSpec
from staffing_agent.node3_occupation import node3_slack_markdown
from staffing_agent.reply_template import ReplyStyle, reply_style
from staffing_agent.slack_phase_c import build_phase_c_section
from staffing_agent.team_capacity import build_live_call_support_markdown, build_live_capacity_markdown
from staffing_agent.thread_context import (
    build_context_reply,
    format_thread_preview,
    gather_google_doc_previews,
    gather_notion_previews,
    phase_b_excerpt_for_llm,
)

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=True)

_ROLE_SHORTLIST_HEADING = {
    "so": "SO",
    "soe": "SoE",
    "dpm": "DPM",
    "wfm": "WFM",
    "qm": "QM",
    "se": "SE",
}


def _src_label(src: str) -> str:
    return {
        "mock": "mock (STAFFING_AGENT_MOCK_LLM=1; no Opus)",
        "llm_unavailable": "LLM unavailable (set ANTHROPIC_API_KEY or use mock flag for tests)",
        "anthropic": "Anthropic Opus",
        "anthropic_fallback": "Anthropic failed — deal-feed heuristic summary",
        "anthropic_rescue": "Anthropic/JSON failed — tier recovered from thread text",
        "error": "error",
    }.get(src, src)


def _canonical_slack_message(
    spec: RequestSpec,
    *,
    lede: str,
    n3_chunks: list[str],
    phase_c: str,
    extraction_src_label: str,
    context_block: str | None = None,
    style: ReplyStyle = "minimal",
) -> str:
    """CR-4 Slack skeleton: 📌 Context · 🎯 Target · 🏷️ Tags · 👥 People · ⚠️ Notes · ➡️ Next.

    ``style=full`` adds Node 2 (Decision Logic) and Phase B ``RequestSpec`` JSON under Context.
    """
    pin_parts: list[str] = []
    if (context_block or "").strip():
        pin_parts.append(context_block.strip())
    outline = spec.phase_b_outline_mrkdwn()
    if outline.strip():
        pin_parts.append(outline)
    # CR-4 full skeleton: Decision Logic (Node 2) + structured Phase B JSON in Context.
    if style == "full":
        n2 = node2_slack_markdown(spec.tier, list(spec.project_type_tags or [])).strip()
        if n2:
            pin_parts.append(n2)
        js = spec.to_slack_block().strip()
        if js:
            pin_parts.append(f"*Phase B — RequestSpec (JSON)*\n{js}")
    pin = "\n\n".join(pin_parts).strip() or "_No pinned context._"
    goal = (lede or "").strip() or "—"
    tags = ", ".join(spec.project_type_tags) if spec.project_type_tags else "—"
    rt = (spec.request_type or "").strip()
    if rt:
        tags = f"{tags} · _{rt}_"
    ppl = "\n\n".join(n3_chunks).strip() if n3_chunks else "—"
    risks = (spec.notes or "").strip() or "—"
    if len(risks) > 700:
        risks = risks[:697] + "…"
    nxt = (phase_c or "").strip() or "—"
    return (
        f"📌 *Context*\n{pin}\n\n"
        f"🎯 *Target*\n{goal}\n\n"
        f"🏷️ *Tags*\n{tags}\n\n"
        f"👥 *People*\n{ppl}\n\n"
        f"⚠️ *Risks / notes*\n{risks}\n\n"
        f"➡️ *Next*\n{nxt}\n\n"
        f"_(Classification source: {extraction_src_label})_"
    )


def _apply_pre_sales_boost_for_rfp_capacity(
    spec: RequestSpec,
    thread_plain: str,
    trigger_message_text: str | None,
) -> RequestSpec:
    """
    Deal / RFP threads often include a capacity ping plus words ``team`` + ``capacity`` + ``available``.
    Route those to pre_sales SO bench instead of org-wide TEAM CAPACITY overview.
    """
    if spec.narrow_staffing_scenario:
        return spec
    if not is_team_capacity_query(thread_plain, trigger_message_text=trigger_message_text):
        return spec
    if not thread_suggests_pre_sales_rfp_deal_shape(thread_plain):
        return spec
    pa = (spec.parsed_ask_summary_en or "").strip()
    if not pa:
        pa = (
            "Pre-sales / RFP-shaped thread with a capacity ping — SO bench first "
            "(not a generic org-wide capacity snapshot)."
        )
    return spec.model_copy(
        update={
            "narrow_staffing_scenario": "pre_sales_shape",
            "parsed_ask_summary_en": pa[:1200],
        }
    )


def _node3_markdown_when_no_tier() -> str:
    """Phase B has no tier and thread did not match capacity / single-role heuristics."""
    return (
        "*Staffing — need a bit more context*\n"
        "_No clear match yet: ask for *team capacity*, a single role (SoE, DPM, …), or add a project tier._\n\n"
        "*Examples:*\n"
        "• `Team capacity` @who_is_available — who is free by role\n"
        "• `Need 1 SoE tier 3 …` — shortlist for one role (and full layout if tier is set)\n"
        "• Thread with deal + tier — staffing layout for the project\n"
    )


def _public_spec_lede(spec: RequestSpec) -> str:
    """Short Slack-visible preamble: optional parsed ask (EN), tier+judge line, else first line of summary."""
    bits: list[str] = []
    pa = (spec.parsed_ask_summary_en or "").strip()
    if pa:
        bits.append(pa)
    th = spec.tier_slack_header_mrkdwn()
    if th:
        bits.append(th)
    elif (spec.summary or "").strip():
        summ = (spec.summary or "").strip()
        first_line = summ.split("\n", 1)[0].strip()
        if len(first_line) > 280:
            first_line = first_line[:277] + "…"
        bits.append(first_line)
    return "\n\n".join(bits)


def _append_full_team_block(
    spec: RequestSpec,
    parts: list[str],
    *,
    thread_plain: str,
    trigger_message_text: str | None,
) -> None:
    want = spec.include_full_team_candidates or thread_suggests_full_team_intent(
        thread_plain, trigger_message_text=trigger_message_text
    )
    if not want:
        return
    if spec.tier is not None:
        parts.append(
            node3_slack_markdown(
                tier=spec.tier,
                project_type_tags=spec.project_type_tags,
                summary=spec.summary,
                sese_path=spec.sese_path,
                skill_rerank_by_email=spec.skill_rerank_by_email or None,
            )
        )
    else:
        parts.extend(build_live_capacity_markdown())


def _resolve_narrow_staffing_parts(
    spec: RequestSpec,
    *,
    thread_plain: str,
    trigger_message_text: str | None,
) -> list[str]:
    sc = spec.narrow_staffing_scenario
    parts: list[str] = []
    if sc == "pre_sales_shape":
        parts.extend(
            build_live_capacity_markdown(
                only_role="so",
                scoping_so_handler=True,
                role_shortlist_title="*Pre-sales / RFP scoping — SO bench*",
                role_shortlist_subtitle=(
                    "_Accountable SO pool (SoE/DPM). "
                    "Handler gate: *fewer than 2* scoping engagements and *no AT_RISK* projects "
                    "(+ BEHIND when `blocked_if_any_at_risk_or_behind` in `decision_logic.yaml`). "
                    "Full team / tier layout: add tier or ask for *team capacity*._"
                ),
            )
        )
        _append_full_team_block(spec, parts, thread_plain=thread_plain, trigger_message_text=trigger_message_text)
        return parts
    if sc == "call_support":
        parts.extend(build_live_call_support_markdown(role_tags=list(spec.call_support_role_tags or [])))
        _append_full_team_block(spec, parts, thread_plain=thread_plain, trigger_message_text=trigger_message_text)
        return parts
    if sc == "single_role":
        spec_mr = [str(x).strip().lower() for x in (spec.narrow_multi_roles or []) if str(x).strip()]
        spec_mr = [x for x in spec_mr if x in _ROLE_SHORTLIST_HEADING]
        roles: list[str] = []
        if len(spec_mr) >= 2:
            roles = list(dict.fromkeys(spec_mr))
        else:
            mr = multi_roles_from_thread(thread_plain)
            if len(mr) >= 2:
                roles = mr
        if not roles:
            role = (
                only_role_from_thread(thread_plain)
                or spec.narrow_single_role
                or single_role_focus_from_thread(thread_plain)
            )
            roles = [role] if role else []
        if not roles:
            parts.append(
                "*Staffing — single role*\n"
                "_Phase B chose `single_role` but no role bucket found — set `narrow_single_role` / "
                "`narrow_multi_roles` or name SoE / DPM / WFM / QM / SE / accountable SO in the thread._"
            )
        else:
            multi = len(roles) >= 2
            for i, role in enumerate(roles):
                if not role:
                    continue
                rlab = _ROLE_SHORTLIST_HEADING.get(role, role.upper())
                title = None
                sub = None
                if multi:
                    title = "*Staffing — role shortlists*" if i == 0 else f"*{rlab}*"
                    sub = (
                        "_1 primary + 2 alternates per role (FREE/PARTIAL)._"
                        if i == 0
                        else f"_{rlab} slice._"
                    )
                parts.extend(
                    build_live_capacity_markdown(
                        only_role=role,
                        role_shortlist_title=title,
                        role_shortlist_subtitle=sub,
                        role_shortlist_compact=True,
                    )
                )
        _append_full_team_block(spec, parts, thread_plain=thread_plain, trigger_message_text=trigger_message_text)
        return parts
    return []


def _resolve_node3_parts(
    spec: RequestSpec,
    *,
    thread_plain: str,
    trigger_message_text: str | None,
) -> list[str]:
    if spec.narrow_staffing_scenario:
        return _resolve_narrow_staffing_parts(
            spec, thread_plain=thread_plain, trigger_message_text=trigger_message_text
        )
    exclusive = only_role_from_thread(thread_plain)
    if exclusive:
        return build_live_capacity_markdown(only_role=exclusive)
    if is_team_capacity_query(thread_plain, trigger_message_text=trigger_message_text):
        return build_live_capacity_markdown()
    role = single_role_focus_from_thread(thread_plain)
    if role and spec.tier is None:
        return build_live_capacity_markdown(only_role=role)
    if spec.tier is None:
        return [_node3_markdown_when_no_tier()]
    return [
        node3_slack_markdown(
            tier=spec.tier,
            project_type_tags=spec.project_type_tags,
            summary=spec.summary,
            sese_path=spec.sese_path,
            skill_rerank_by_email=spec.skill_rerank_by_email or None,
        )
    ]


def build_slack_mention_reply(
    messages: list[dict[str, Any]],
    previews: list[dict[str, Any]],
    spec: RequestSpec,
    *,
    extraction_src_label: str,
    google_previews: list[dict[str, Any]] | None = None,
    thread_plain: str | None = None,
    trigger_message_text: str | None = None,
) -> list[str]:
    """
    Socket Mode + paste: shape depends on STAFFING_AGENT_REPLY_STYLE.

    Returns one or more Slack ``text`` payloads (team capacity: overview + one or more detail chunks).
    """
    tp = (thread_plain or "").strip() or format_thread_preview(messages)
    trig = trigger_message_text

    spec = _apply_pre_sales_boost_for_rfp_capacity(spec, tp, trig)
    n3_list = _resolve_node3_parts(spec, thread_plain=tp, trigger_message_text=trig)
    lede = _public_spec_lede(spec)
    rs = reply_style()

    phase_c = build_phase_c_section()

    if rs == "minimal" or rs == "compact":
        if not n3_list:
            return [
                _canonical_slack_message(
                    spec,
                    lede=lede,
                    n3_chunks=["—"],
                    phase_c=phase_c,
                    extraction_src_label=extraction_src_label,
                    style=rs,
                )
            ]
        pc_first = phase_c if len(n3_list) == 1 else ""
        first_msg = _canonical_slack_message(
            spec,
            lede=lede,
            n3_chunks=[n3_list[0]],
            phase_c=pc_first,
            extraction_src_label=extraction_src_label,
            style=rs,
        )
        if len(n3_list) == 1:
            return [first_msg]
        rest = list(n3_list[1:])
        rest[-1] = rest[-1] + "\n\n" + phase_c
        return [first_msg] + rest

    ctx = (
        build_context_reply(messages, previews=previews, google_previews=google_previews).strip() or None
    )
    if not n3_list:
        return [
            _canonical_slack_message(
                spec,
                lede=lede,
                n3_chunks=["—"],
                phase_c=phase_c,
                extraction_src_label=extraction_src_label,
                context_block=ctx,
                style="full",
            )
        ]
    pc_first = phase_c if len(n3_list) == 1 else ""
    first_full = _canonical_slack_message(
        spec,
        lede=lede,
        n3_chunks=[n3_list[0]],
        phase_c=pc_first,
        extraction_src_label=extraction_src_label,
        context_block=ctx,
        style="full",
    )
    if len(n3_list) == 1:
        return [first_full]
    rest_f = list(n3_list[1:])
    rest_f[-1] = rest_f[-1] + "\n\n" + phase_c
    return [first_full] + rest_f


def build_reply_from_paste(thread_text: str, *, notion_excerpt_override: str = "") -> tuple[str, str]:
    """
    Build the same mrkdwn body the bot would post for a thread whose text is `thread_text`.
    Returns (reply_text, extraction_source). Multiple bot messages are joined with a divider line.
    """
    text = (thread_text or "").strip()
    messages: list[dict[str, Any]] = [{"user": "paste", "text": text}]
    previews = gather_notion_previews(messages)
    google_previews = gather_google_doc_previews(messages)
    notion_ex = (notion_excerpt_override or "").strip() or phase_b_excerpt_for_llm(
        messages,
        notion_previews=previews,
        google_previews=google_previews,
    )
    thread_plain = format_thread_preview(messages)
    spec, src = extract_request_spec(thread_plain, notion_ex)
    parts = build_slack_mention_reply(
        messages,
        previews,
        spec,
        extraction_src_label=_src_label(src),
        google_previews=google_previews,
        thread_plain=thread_plain,
    )
    reply = "\n\n────────\n\n".join(parts)
    return reply, src


def post_reply_to_slack(channel: str, text: str) -> None:
    """Post one or more messages as the bot (needs SLACK_BOT_TOKEN; bot must be in the channel)."""
    from slack_sdk import WebClient

    token = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set")
    client = WebClient(token=token)
    parts = text.split("\n\n────────\n\n")
    for chunk in parts:
        resp = client.chat_postMessage(channel=channel.strip(), text=chunk)
        if not resp.get("ok"):
            raise RuntimeError(resp)
