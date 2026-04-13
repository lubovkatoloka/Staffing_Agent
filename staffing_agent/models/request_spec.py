"""Structured output for Node 1–2 (classification + tags) — phase B."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RequestSpec(BaseModel):
    """LLM extraction from Slack thread (+ optional Notion excerpts)."""

    tier: Optional[int] = Field(None, description="Project tier 1–4 (required when there is staffing/project context)")
    complexity_class: Optional[Literal["S", "M", "L"]] = Field(
        None,
        description="Framework complexity S/M/L; set when tier is set",
    )
    tier_rationale: str = Field(
        "",
        description="Node 1: why this tier + complexity (1–4 sentences)",
    )
    project_type_tags: List[str] = Field(default_factory=list)
    summary: str = Field("", description="One short paragraph")
    project_start_hint: Optional[str] = Field(
        None, description="ISO date or free-text timing hint if any"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    notes: str = Field("", description="Ambiguity, missing info, assumptions")

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
