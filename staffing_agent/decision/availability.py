"""
Node 3 — availability tiers (occupation + PTO + SOFT + UNVERIFIED).

Inputs are *already combined* where the spec says to combine (e.g. total occupation
including PTO coefficient). SQL to compute those values stays in Databricks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from staffing_agent.decision.enums import AvailabilityLabel


@dataclass(frozen=True)
class Availability:
    label: AvailabilityLabel
    """Resolved label after applying spec priority."""

    total_occupation: float
    """0..1 combined project + PTO coefficient when applicable."""

    notes: str = ""


def _band_from_occupation(total: float, occ_cfg: Mapping[str, Any]) -> AvailabilityLabel:
    free_max = float(occ_cfg.get("free_below", 0.5))
    partial_max = float(occ_cfg.get("partial_below", 0.8))
    if total < free_max:
        return AvailabilityLabel.FREE
    if total < partial_max:
        return AvailabilityLabel.PARTIAL
    return AvailabilityLabel.BUSY


def classify_availability(
    total_occupation: float,
    *,
    active_project_count: int = 0,
    pto_full_week: bool = False,
    has_soft_assignment: bool = False,
    decision_cfg: Optional[Mapping[str, Any]] = None,
) -> Availability:
    """
    Apply Decision Logic v1.0 priority (subset implemented in code):

    1. Full-week PTO → PTO (caller may exclude candidate entirely).
    2. UNVERIFIED → 0% occupation and 0 active projects (spec: ghost / not logged).
    3. SOFT → any assignment on discovery / BLOCKED_CLIENT / close_out (flag from caller).
    4. Else FREE / PARTIAL / BUSY from occupation bands.

    `total_occupation` is expected in [0, 1]. Out-of-range values are clamped for band math only.
    """
    cfg = decision_cfg or {}
    occ_cfg = cfg.get("occupation") or {}
    unv_cfg = cfg.get("unverified") or {}

    if pto_full_week:
        return Availability(
            label=AvailabilityLabel.PTO,
            total_occupation=max(0.0, min(1.0, total_occupation)),
            notes="full_week_pto",
        )

    t = max(0.0, min(1.0, float(total_occupation)))

    if unv_cfg.get("when_occupation_zero") and unv_cfg.get("when_active_projects_zero"):
        if t == 0.0 and active_project_count == 0:
            return Availability(
                label=AvailabilityLabel.UNVERIFIED,
                total_occupation=t,
                notes="zero_occ_zero_projects",
            )

    if has_soft_assignment:
        return Availability(
            label=AvailabilityLabel.SOFT,
            total_occupation=t,
            notes="soft_stage_or_status",
        )

    band = _band_from_occupation(t, occ_cfg)
    return Availability(label=band, total_occupation=t, notes="")


def soft_assignment_match(
    *,
    stage: str | None,
    status: str | None,
    decision_cfg: Mapping[str, Any],
) -> bool:
    """True if this project role matches SOFT row (discovery / blocked_client / close_out)."""
    soft = decision_cfg.get("soft_assignment") or {}
    stages = {str(s).lower() for s in (soft.get("stages") or [])}
    statuses = {str(s).upper() for s in (soft.get("statuses") or [])}
    st = (stage or "").strip().lower()
    stat = (status or "").strip().upper()
    if st in stages:
        return True
    if stat in statuses:
        return True
    # close_out naming variants in raw data
    if "close_out" in st or st.startswith("close_out"):
        return True
    return False
