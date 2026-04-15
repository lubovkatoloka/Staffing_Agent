"""Slack copy for Node 3 checklist + Node 4 / 4.5 / 5 (Decision Logic v1.0) — next-step guidance."""

from __future__ import annotations

from typing import Optional

NOTION_DL = "https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4"


def node3_checklist_intro() -> str:
    return (
        "*Node 3 — what we do (per spec)*\n"
        "1. *Occupation SQL* — matrix coefficients, total load by role on projects.\n"
        "2. *PTO SQL* — who is on PTO / out today (separate query below).\n"
        "3. The final table already has `project_occupation`, `pto`, and total `occupation` "
        "(as in Notion: total = project + PTO coefficient).\n"
        "4. Bands *FREE / PARTIAL / BUSY / …* — from `config/decision_logic.yaml`; "
        "*UNVERIFIED* at 0% without confirmed load — per spec, not FREE.\n"
        "5. *Tier from Phase B (Node 1)* defines *who we staff*; the Occupation table below, when Tier is known, "
        "shows only Node 2 roles (e.g. Tier 2 → SoE/DPM).\n"
        f"_Full spec:_ <{NOTION_DL}|Decision Logic v1.0>\n"
    )


def node4_section_markdown(tier: Optional[int]) -> str:
    tier_hint = ""
    if tier == 2:
        tier_hint = (
            "_Your Tier 2: minimum team = *SO (SoE or DPM)*; "
            "WFM/QM are not required in Tier 2 by default for “is there a match”._\n"
        )
    lines = [
        "*Node 4 — Is there a match?*",
        "*Target composition by Tier (from spec):*",
        "• Tier 1 — SO (DPM or WFM) + WFM + QM · ~1.3 FTE",
        "• Tier 2 — SO (SoE or DPM) + WFM + QM when not SeSe · ~1.3 FTE (or <1 with SeSe)",
        "• Tier 3 — SO (SSoE or DPM) + SoE + WFM · ~1.7 FTE",
        "• Tier 4 — SO (SSoE or DPM) + SoE + WFM + SE · ~3 FTE",
        "",
        "*Match* = for each *required* role there is at least one *FREE* or *SOFT* candidate.",
        "*If YES* — propose a team; *if NO* — which roles are open → Node 5.",
        "",
        "*Ranking (Tier 1–2, domain optional):* availability → SO status → seniority.",
        "*Ranking (Tier 3–4):* *domain / tag overlap* first, then availability → SO status → seniority.",
        tier_hint,
        f"_Details:_ <{NOTION_DL}|Decision Logic — Node 4>",
    ]
    return "\n".join(lines)


def node4_5_section_markdown() -> str:
    return (
        "*Node 4.5 — Freeing up soon*\n"
        "_People who are busy now but free up within ~8 weeks — for forward planning._\n"
        f"_Spec:_ <{NOTION_DL}|Node 4.5>"
    )


def node5_section_markdown() -> str:
    return (
        "*Node 5 — Can we rebalance?*\n"
        "If there is no full match: can we *free* someone from SOFT/BUSY (donors: deadline this week, "
        "discovery/scoping as donors, AT_RISK/BEHIND blocks, etc.).\n"
        "*If NO* — escalate to Directors / Delivery Leads.\n"
        f"_Spec:_ <{NOTION_DL}|Node 5>"
    )


def node3_checklist_intro_compact() -> str:
    """One paragraph instead of the long Node 3 checklist."""
    return (
        "_Load: Occupation SQL + PTO in Databricks; FREE/PARTIAL bands from `config/decision_logic.yaml`; "
        f"Tier from Phase B sets the role filter. Spec: <{NOTION_DL}|Decision Logic v1.0>._"
    )


def followup_decision_nodes_compact(tier: Optional[int]) -> str:
    """Node 4–5 without tables — links and one line on match."""
    th = ""
    if tier == 2:
        th = "_Tier 2: one SO (SoE or DPM) is enough._ "
    return (
        "*Next in Decision Logic*\n"
        f"{th}"
        "• Node 4 — team match / ranking — "
        f"<{NOTION_DL}|spec>\n"
        f"• Node 4.5 — freeing up soon — <{NOTION_DL}|spec>\n"
        f"• Node 5 — rebalance — <{NOTION_DL}|spec>\n"
        "_Full tables and exports are in Databricks / Notion, not in this message._"
    )
