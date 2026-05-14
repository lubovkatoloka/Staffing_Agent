"""Structured output for Node 1–2 (classification + tags) — phase B."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

NarrowStaffingScenario = Literal["pre_sales_shape", "call_support", "single_role"]
NarrowSingleRoleKey = Literal["so", "soe", "dpm", "wfm", "qm", "se"]


class RequestSpec(BaseModel):
    """LLM extraction from Slack thread (+ optional Notion excerpts)."""

    thread_kind: Optional[
        Literal["deal_notification", "staffing_request", "capacity_question", "unclear"]
    ] = Field(
        None,
        description=(
            "Step 0 — what the thread is: deal_notification (Attio/CRM/exploration), "
            "staffing_request (explicit resourcing), capacity_question (who's free / capacity), "
            "unclear. Set capacity_question only if the thread is primarily a capacity ask; "
            "the app may route capacity without LLM when phrases match."
        ),
    )
    tier: Optional[int] = Field(None, description="Project tier 1–4 (required when there is staffing/project context)")
    complexity_class: Optional[Literal["S", "M", "L"]] = Field(
        None,
        description="Framework complexity S/M/L; set when tier is set",
    )
    tier_rationale: str = Field(
        "",
        description=(
            "Node 1: why this tier + complexity (S/M/L). May include SCQA-style reasoning and framework signals "
            "(pipeline, QC, expertise, client, infra) per Project Classification Framework — often several sentences "
            "or short bullets; keep summary short and put depth here."
        ),
    )
    project_type_tags: List[str] = Field(default_factory=list)
    judge: str = Field(
        "",
        max_length=80,
        description=(
            "Single-line request label for Slack (≤80 chars): "
            "`<client> <project_type> · <key_signal>` — no SCQA prose."
        ),
    )
    sese_path: bool = Field(
        False,
        description="Tier 2 SeSe lean team (SO-only template) when applicable.",
    )
    summary: str = Field("", description="One short paragraph (internal / logs; not shown in slim Slack replies)")
    project_start_hint: Optional[str] = Field(
        None, description="ISO date or free-text timing hint if any"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    notes: str = Field(
        "",
        description="Ambiguity, risk flags, what to clarify with the client, or assumptions not in tier_rationale.",
    )
    narrow_staffing_scenario: Optional[NarrowStaffingScenario] = Field(
        None,
        description=(
            "Phase B narrow staffing path: pre_sales_shape (RFP/scoping — SO bench), "
            "call_support (SO bench + People & Tags slices from call_support_role_tags), "
            "single_role (one role shortlist; optionally full team block when tier or full-team intent)."
        ),
    )
    parsed_ask_summary_en: str = Field(
        "",
        description="One or two sentences in English: what Delivery should do (shown in slim Slack after classification).",
    )
    include_full_team_candidates: bool = Field(
        False,
        description=(
            "When true with a narrow scenario, append full Node 3 layout (if tier set) or full team capacity (tier null)."
        ),
    )
    call_support_role_tags: List[str] = Field(
        default_factory=list,
        description=(
            "For call_support: which People & Tags role_tag slices to show after the SO bench — "
            "SSOE+SOE, DPM, SOE (explicit SoE-shaped pool). Subset only; app ignores unknown labels."
        ),
    )
    narrow_single_role: Optional[NarrowSingleRoleKey] = Field(
        None,
        description="For single_role scenario: primary bucket so|soe|dpm|wfm|qm|se (thread regex used only as fallback).",
    )
    narrow_multi_roles: List[NarrowSingleRoleKey] = Field(
        default_factory=list,
        description=(
            "For single_role: ordered role list when the ask names 2+ buckets (e.g. SoE + DPM). "
            "App shows one compact shortlist per role. Thread parser fills when Phase B omits this."
        ),
    )
    request_type: str = Field(
        "",
        description="CRM/Attio request classification or deal type label from Phase B (plain language).",
    )
    attio_deal_id: str = Field("", description="Attio deal / object id when present in thread or CRM paste.")
    attio_deal_name: str = Field("", description="Deal name from Attio or CRM header.")
    attio_company_name: str = Field("", description="Company / account name from Attio.")
    attio_deal_value: str = Field("", description="Deal value as text from CRM (keep currency with number).")
    attio_currency: str = Field("", description="ISO or symbol currency if split from value.")
    attio_stage: str = Field("", description="Pipeline stage or deal stage.")
    attio_owner: str = Field("", description="Deal owner or primary contact name/email.")
    attio_source: str = Field("", description="Lead or deal source.")
    attio_expected_close: str = Field("", description="Expected close date (ISO or free text).")
    attio_pipeline: str = Field("", description="Pipeline or business line name.")
    attio_territory: str = Field("", description="Region or territory.")
    attio_industry: str = Field("", description="Industry / segment.")
    attio_notes: str = Field("", description="Short CRM notes or qualification snippet.")
    attio_record_url: str = Field("", description="Deep link to deal in Attio or CRM if present.")
    attio_created_at: str = Field("", description="Record created timestamp string if present.")
    skill_rerank_by_email: dict[str, float] = Field(
        default_factory=dict,
        description="Optional per-email 0..1 LLM skill rerank for Node 4 (|∩| + 0.5×this).",
    )

    @field_validator("tier")
    @classmethod
    def tier_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if not 1 <= v <= 4:
            raise ValueError("tier must be 1..4 or null")
        return v

    def to_slack_block(self) -> str:
        data = self.model_dump()
        import json

        return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"

    def phase_b_outline_mrkdwn(self) -> str:
        """Human-readable Phase B summary for Slack (no raw JSON)."""
        lines: list[str] = []
        if self.thread_kind:
            lines.append(f"• *Kind:* {self.thread_kind}")
        if self.request_type.strip():
            lines.append(f"• *Request type:* {(self.request_type or '').strip()}")
        if self.tier is not None:
            cc = self.complexity_class or "?"
            lines.append(f"• *Tier / class:* {self.tier} · {cc}")
        if (self.judge or "").strip():
            lines.append(f"• *Label:* {(self.judge or '').strip()}")
        if self.project_type_tags:
            lines.append(f"• *Tags:* {', '.join(self.project_type_tags)}")
        nm = [str(x).strip() for x in (self.narrow_multi_roles or []) if str(x).strip()]
        if len(nm) >= 2:
            lines.append(f"• *Role shortlists:* {', '.join(nm)}")
        attio_bits: list[str] = []
        for label, val in (
            ("Deal", (self.attio_deal_name or "").strip() or (self.attio_deal_id or "").strip()),
            ("Company", (self.attio_company_name or "").strip()),
            ("Value", (self.attio_deal_value or "").strip()),
            ("Stage", (self.attio_stage or "").strip()),
            ("Owner", (self.attio_owner or "").strip()),
        ):
            if val:
                attio_bits.append(f"{label}: {val}")
        if attio_bits:
            lines.append(f"• *CRM:* {' · '.join(attio_bits)}")
        summ = (self.summary or "").strip()
        if summ:
            clip = summ[:400] + ("…" if len(summ) > 400 else "")
            lines.append(f"• *Summary:* {clip}")
        if not lines:
            return "_No Phase B classification detail._"
        return "\n".join(lines)

    def tier_slack_header_mrkdwn(self) -> str | None:
        """CR-4 tier line for Slack: tier · complexity · staffing template — judge."""
        from staffing_agent.decision.team_template import team_template_string

        if self.tier is None:
            return None
        cc = self.complexity_class or "?"
        team_str = team_template_string(self.tier, sese_path=self.sese_path)
        judge = (self.judge or "").strip()
        if judge:
            return f"*Tier {self.tier} · {cc}: {team_str}* — {judge}"
        return f"*Tier {self.tier} · {cc}: {team_str}*"

    def to_slack_brief(self) -> str:
        """Legacy brief (full style). Slim @mention replies use `tier_slack_header_mrkdwn()` instead."""
        parts: list[str] = []
        if self.tier is not None:
            tier_line = f"*Tier {self.tier}*"
            if self.complexity_class:
                tier_line += f" · class {self.complexity_class}"
            parts.append(tier_line)
        if self.project_type_tags:
            parts.append("_Request type:_ " + ", ".join(self.project_type_tags))
        summ = (self.summary or "").strip()
        tr = (self.tier_rationale or "").strip()
        if summ and tr:
            body = f"{summ}\n\n{tr}" if tr not in summ else summ
        elif summ:
            body = summ
        else:
            body = tr
        if body:
            parts.append(body)
        return "\n".join(parts) if parts else "_No brief summary in Phase B._"
