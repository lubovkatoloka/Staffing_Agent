"""Capacity v2 decision module — replaces availability.py.

Source spec: https://www.notion.so/34b49d06885681468dd6d79d2e16d332
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from staffing_agent.decision.enums import Band, IneligibleReason, SoftReason


@dataclass(frozen=True)
class CapacityRow:
    """One project assignment a person currently has."""

    project_id: str
    project_name: str
    tier: str  # "Tier 1" .. "Tier 4"
    stage: str  # building | stabilisation_delivery | ...
    status: str  # ON_TRACK | AT_RISK | ...


@dataclass(frozen=True)
class CapacityVerdict:
    capacity_used: float
    band: Band
    total_projects: int
    scoping_count: int
    has_at_risk_or_behind: bool
    on_pto_today: bool
    pto_upcoming_dates: Optional[tuple[str, str]]  # (YYYY-MM-DD, YYYY-MM-DD) if upcoming PTO within window
    in_hard_exclude: bool
    is_soft: bool
    soft_reasons: tuple[SoftReason, ...] = field(default_factory=tuple)
    eligible_for_new: bool = True
    ineligible_reason: IneligibleReason = IneligibleReason.OK


def _norm_stage(stage: str) -> str:
    s = (stage or "").strip().lower().replace(" ", "_").replace("-", "_")
    return s


def _norm_status(status: str) -> str:
    return (status or "").strip().upper()


def _tier_weight(tier: str, tier_weights: Mapping[str, Any]) -> float:
    t = (tier or "").strip()
    if t not in tier_weights:
        return 0.0
    try:
        return float(tier_weights[t])
    except (TypeError, ValueError):
        return 0.0


def _stage_status_multiplier(stage: str, status: str, matrix: Mapping[str, Any]) -> float:
    st = _norm_stage(stage)
    stat = _norm_status(status)
    row = matrix.get(st)
    if row is None or not isinstance(row, Mapping):
        return 0.0
    raw = row.get(stat)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def compute_capacity(rows: list[CapacityRow], cfg: Mapping) -> float:
    """Sum tier_weight * stage_status_multiplier across rows. Unknown tier/stage/status contribute 0."""
    tw = cfg.get("tier_weights") or {}
    mx = cfg.get("stage_status_matrix") or {}
    total = 0.0
    for r in rows:
        w = _tier_weight(r.tier, tw)
        m = _stage_status_multiplier(r.stage, r.status, mx)
        total += w * m
    return total


def classify_band(capacity_used: float, cfg: Mapping) -> Band:
    """Map capacity to FREE/PARTIAL/AT_CAP using availability_bands from cfg.

    Boundary: capacity_used == free_below -> PARTIAL (strict); capacity_used == partial_below -> AT_CAP.
    """
    bands = cfg.get("availability_bands") or {}
    free_below = float(bands.get("free_below", 1.0))
    partial_below = float(bands.get("partial_below", 2.0))
    c = float(capacity_used)
    if c < free_below:
        return Band.FREE
    if c < partial_below:
        return Band.PARTIAL
    return Band.AT_CAP


def _detect_soft(rows: list[CapacityRow], capacity_used: float, cfg: Mapping) -> tuple[bool, tuple[SoftReason, ...]]:
    """Apply soft_signal.triggers from cfg."""
    triggers_cfg = ((cfg.get("soft_signal") or {}).get("triggers")) or []
    triggers = {str(t).strip() for t in triggers_cfg}
    reasons: list[SoftReason] = []
    total = len(rows)
    if total == 0:
        return False, ()

    if "all_scoping_or_discovery" in triggers:
        if capacity_used == 0.0 and total > 0:
            if all(_norm_stage(r.stage) in ("scoping_solution_design", "discovery") for r in rows):
                reasons.append(SoftReason.ALL_SCOPING_OR_DISCOVERY)

    if "all_close_out_on_track" in triggers:
        if total > 0 and all(
            _norm_stage(r.stage) == "close_out_retrospective" and _norm_status(r.status) == "ON_TRACK"
            for r in rows
        ):
            reasons.append(SoftReason.ALL_CLOSE_OUT_ON_TRACK)

    return (bool(reasons), tuple(reasons))


def assess(
    rows: list[CapacityRow],
    *,
    on_pto_today: bool,
    pto_upcoming: Optional[tuple[str, str]],
    in_hard_exclude: bool,
    new_project_weight: float,
    cfg: Mapping,
) -> CapacityVerdict:
    """Single entry point that callers use.

    Eligibility precedence (first match wins):
      1. in_hard_exclude         -> IN_HARD_EXCLUDE
      2. on_pto_today            -> ON_PTO_TODAY
      3. total_projects >= max   -> MAX_PROJECTS_CAP
      4. capacity_used + new_project_weight > cap_units -> CAPACITY_OVERFLOW
      5. otherwise               -> OK / eligible
    """
    row_list = list(rows)
    capacity_used = compute_capacity(row_list, cfg)
    band = classify_band(capacity_used, cfg)
    total_projects = len(row_list)
    scoping_count = sum(1 for r in row_list if _norm_stage(r.stage) == "scoping_solution_design")
    has_at_risk_or_behind = any(_norm_status(r.status) in ("AT_RISK", "BEHIND") for r in row_list)

    hard_rules = cfg.get("hard_rules") or {}
    max_projects = int(hard_rules.get("max_total_active_projects", 4))
    cap_units = float(cfg.get("cap_units", 2.0))
    npw = float(new_project_weight)

    is_soft, soft_reasons = _detect_soft(row_list, capacity_used, cfg)

    eligible = True
    ineligible_reason = IneligibleReason.OK

    if in_hard_exclude:
        eligible = False
        ineligible_reason = IneligibleReason.IN_HARD_EXCLUDE
    elif on_pto_today:
        eligible = False
        ineligible_reason = IneligibleReason.ON_PTO_TODAY
    elif total_projects >= max_projects:
        eligible = False
        ineligible_reason = IneligibleReason.MAX_PROJECTS_CAP
    elif capacity_used + npw > cap_units:
        eligible = False
        ineligible_reason = IneligibleReason.CAPACITY_OVERFLOW

    return CapacityVerdict(
        capacity_used=capacity_used,
        band=band,
        total_projects=total_projects,
        scoping_count=scoping_count,
        has_at_risk_or_behind=has_at_risk_or_behind,
        on_pto_today=on_pto_today,
        pto_upcoming_dates=pto_upcoming,
        in_hard_exclude=in_hard_exclude,
        is_soft=is_soft,
        soft_reasons=soft_reasons,
        eligible_for_new=eligible,
        ineligible_reason=ineligible_reason,
    )
