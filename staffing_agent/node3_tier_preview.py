"""
Tier → `project_role` filter for the Node 3 occupation *table preview* only.

Aligned with Node 2 (Decision Logic). Full SQL result is unchanged; we only narrow the first 15 rows in Slack.
Tier comes from Phase B (Node 1 extraction).
"""

from __future__ import annotations

from typing import Optional

# Normalized project_role values from occupation SQL (employees + staffing join).
# Aligned with Tier / Ownership model (Decision Logic): SO pool + supporting roles per tier.
_PREVIEW_BY_TIER: dict[int, frozenset[str]] = {
    # Tier 1 · S — client platform / raw supply: SO = DPM or WFM; + WFM + QM
    1: frozenset({"dpm", "wfm", "qm"}),
    # Tier 2 · S — standard pipeline: SO = SoE or DPM; + WFM + QM when not SeSe path (show full team roles)
    2: frozenset({"soe", "dpm", "wfm", "qm"}),
    # Tier 3 · M — multi-stage / domain: SO = SSoE or DPM; + SoE + WFM (WFC)
    3: frozenset({"dpm", "soe", "wfm"}),
    # Tier 4 · L — strategic: SO = SSoE or DPM; + SoE + WFM + SE (use `project_role` = se in SQL if present)
    4: frozenset({"dpm", "soe", "wfm", "se"}),
}


def occupation_preview_roles(tier: Optional[int]) -> Optional[frozenset[str]]:
    """
    Roles to include in the occupation preview. None = show all rows (no tier or unknown tier).
    """
    if tier is None:
        return None
    return _PREVIEW_BY_TIER.get(tier)


def occupation_preview_caption_suffix(tier: Optional[int], *, max_shown: int = 15) -> str:
    """Short Slack subline explaining the preview filter."""
    roles = occupation_preview_roles(tier)
    if roles is None:
        return f"show {max_shown}, sorted by occupation ↑"
    parts = ", ".join(sorted(roles))
    return f"Tier {tier} preview — roles [{parts}] only; show {max_shown}, sorted by occupation ↑"
