"""
Node 2 — required roles & pool rules from Decision Logic v1.0 (tables in Notion).
Pure text for Slack; candidate names come from Node 3 + HR systems later.
"""

from __future__ import annotations

from typing import Optional


def node2_slack_markdown(tier: Optional[int], project_type_tags: list[str]) -> str:
    """Markdown block for Slack: Node 2 candidate-pool rules for this tier."""
    tags = ", ".join(project_type_tags) if project_type_tags else "_(no tags yet)_"
    if tier is None:
        return (
            "*Node 2 — candidate pool (Decision Logic)*\n"
            "_Set tier in Phase B to see required roles and domain-match rules._\n"
            f"_Project type tags:_ {tags}"
        )

    rows: dict[int, str] = {
        1: (
            "*Required roles:* SO = DPM or WFM; WFM + QM (scoping & building).\n"
            "*Source pool:* people from *similar completed Tier 1* projects.\n"
            "*Domain match:* not required — any available SO."
        ),
        2: (
            "*Required roles:* SO = SoE or DPM (if SeSe applicable per your rules).\n"
            "*Source pool:* any available SoE / DPM with SO status "
            "(SeSe path: SO only — no WFM/QM needed).\n"
            "*Domain match:* not required — any available SO."
        ),
        3: (
            "*Required roles:* SO = SSoE or DPM; SoE + WFM.\n"
            "*Source pool:* people from *similar completed projects* with matching type tags.\n"
            "*Domain match:* **required** — filter by tag overlap / semantic match (Phase 2 in product roadmap)."
        ),
        4: (
            "*Required roles:* SO = DPM; SSoE + SoE + WFM + Commercial.\n"
            "*Source pool:* people from *similar completed projects* with matching type tags.\n"
            "*Domain match:* **required**."
        ),
    }
    body = rows.get(tier, "_Unknown tier._")
    return (
        f"*Node 2 — candidate pool (Decision Logic, Tier {tier})*\n"
        f"{body}\n"
        f"_Project type tags (for domain match when required):_ {tags}"
    )
