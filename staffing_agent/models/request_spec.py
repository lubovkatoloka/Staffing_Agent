"""Structured output for Node 1–2 (classification + tags) — phase B."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
