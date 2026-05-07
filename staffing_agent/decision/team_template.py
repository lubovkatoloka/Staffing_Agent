"""Required staffing team composition by tier.

Drives the header line in Slack output and the role sections that follow.
Single source of truth for which roles to fan-out recommendations across.

Quality roles (QC+QM merged tag in Notion People & Tags) are canonical
for T1/T2 per spec but intentionally EXCLUDED from this rendering
iteration — see backlog. Will be added back when Quality-role tracking
+ ranking infrastructure is wired (post-v2).
"""

from __future__ import annotations

# Canonical role slots per tier. SO is always first.
# These match the v2 spec S4 table, minus Quality (QC+QM) — parked in backlog.
TEAM_TEMPLATES: dict[int, tuple[str, ...]] = {
    1: ("DPM/WFM (SO)", "WFM"),  # Quality (QC+QM) dropped — backlog
    2: ("SoE/DPM (SO)", "WFM"),  # Quality (QC+QM) dropped — backlog
    3: ("SSoE/DPM (SO)", "SoE", "WFM"),
    4: ("SSoE/DPM (SO)", "SoE", "WFM", "SE"),
}

# SeSe path: leaner team, SO only.
TEAM_TEMPLATES_SESE: dict[int, tuple[str, ...]] = {
    2: ("SoE/DPM (SO)",),
}


def team_template_for(tier: int, sese_path: bool = False) -> tuple[str, ...]:
    """Return the ordered tuple of required role slots for a given tier."""
    if sese_path and tier in TEAM_TEMPLATES_SESE:
        return TEAM_TEMPLATES_SESE[tier]
    return TEAM_TEMPLATES.get(tier, ())


def team_template_string(tier: int, sese_path: bool = False) -> str:
    """Return the staffing team as a compact string for the Slack header.

    Examples:
        team_template_string(2) -> "SoE/DPM + WFM"
        team_template_string(4) -> "SSoE/DPM + SoE + WFM + SE"
        team_template_string(2, sese_path=True) -> "SoE/DPM"
    """
    slots = team_template_for(tier, sese_path)
    # Strip "(SO)" suffix from the SO slot for the header — it's implied.
    cleaned = tuple(s.replace(" (SO)", "") for s in slots)
    return " + ".join(cleaned)


# Mapping from team-template slot label to the role-section header used in Slack.
# This determines the "*SO Recommendations*", "*WFM Recommendations*" headings.
SLOT_TO_SECTION_HEADER: dict[str, str] = {
    "DPM/WFM (SO)": "SO Recommendations",
    "SoE/DPM (SO)": "SO Recommendations",
    "SSoE/DPM (SO)": "SO Recommendations",
    "WFM": "WFM Recommendations",
    "SoE": "SoE Recommendations",
    "SE": "SE Recommendations",
    # Note: no QM/QC keys — Quality role section is not rendered in this iteration.
}
