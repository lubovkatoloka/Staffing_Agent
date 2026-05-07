"""Slack copy for Node 3 checklist + Node 4 / 4.5 / 5 (Capacity v2) — next-step guidance."""

from __future__ import annotations

from typing import Optional

NOTION_V2 = "https://www.notion.so/34b49d06885681468dd6d79d2e16d332"


def node3_checklist_intro() -> str:
    return (
        "*Node 3 — what we do (Capacity v2)*\n"
        "1. *capacity.sql* — one row per person × active project; tier weight × stage/status multiplier summed to `capacity_used`.\n"
        "2. *PTO* — flags from HiBob in the same query (`on_pto_today`, upcoming window).\n"
        "3. Bands *FREE / PARTIAL / AT_CAP* — unbounded scale; thresholds in `config/decision_logic.yaml`.\n"
        "4. Hard rules — max concurrent projects, overflow vs `cap_units`, CSV exclusions.\n"
        "5. *Tier from Phase B (Node 1)* defines *who we staff*; the Capacity table below, when Tier is known, "
        "shows only Node 2 roles (e.g. Tier 2 → SoE/DPM).\n"
        f"_Full spec:_ <{NOTION_V2}|Staffing Agent v2 — Capacity>\n"
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
        "*Match* = for each *required* role there is at least one *FREE* or *PARTIAL* candidate eligible for a new project.",
        "*If YES* — propose a team; *if NO* — which roles are open → Node 5.",
        "",
        "*Ranking (Tier 1–2, domain optional):* band → capacity_used → SO status → skills/tags.",
        "*Ranking (Tier 3–4):* *domain / tag overlap* first, then band → capacity_used → SO status.",
        tier_hint,
        f"_Details:_ <{NOTION_V2}|Capacity v2 — Node 4>",
    ]
    return "\n".join(lines)


def node4_5_section_markdown() -> str:
    return (
        "*Node 4.5 — Freeing up soon*\n"
        "_People who are busy now but free up within ~8 weeks — for forward planning._\n"
        f"_Spec:_ <{NOTION_V2}|Node 4.5>"
    )


def node5_section_markdown() -> str:
    return (
        "*Node 5 — Can we rebalance?*\n"
        "If there is no full match: can we *free* someone from AT_CAP / heavy delivery (donors: deadline this week, "
        "discovery/scoping as donors, AT_RISK/BEHIND blocks, etc.).\n"
        "*If NO* — escalate to Directors / Delivery Leads.\n"
        f"_Spec:_ <{NOTION_V2}|Node 5>"
    )


def node3_checklist_intro_compact() -> str:
    """One paragraph instead of the long Node 3 checklist."""
    return (
        "_Load: `capacity.sql` in Databricks; FREE/PARTIAL/AT_CAP from `config/decision_logic.yaml`; "
        f"Tier from Phase B sets the role filter. Spec: <{NOTION_V2}|Staffing Agent v2>._"
    )


def followup_decision_nodes_compact(tier: Optional[int]) -> str:
    """Node 4–5 without tables — links and one line on match."""
    th = ""
    if tier == 2:
        th = "_Tier 2: one SO (SoE or DPM) is enough._ "
    return (
        "*Next — staffing decision flow*\n"
        f"{th}"
        "• Node 4 — team match / ranking — "
        f"<{NOTION_V2}|spec>\n"
        f"• Node 4.5 — freeing up soon — <{NOTION_V2}|spec>\n"
        f"• Node 5 — rebalance — <{NOTION_V2}|spec>\n"
        "_Full tables and exports are in Databricks / Notion, not in this message._"
    )
