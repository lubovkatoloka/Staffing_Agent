import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import (
    Band,
    CapacityRow,
    IneligibleReason,
    SoftReason,
    assess,
    classify_band,
    compute_capacity,
)


@pytest.fixture
def cfg():
    return load_decision_config()


def _row(tier, stage, status, project_id="p1", project_name="P1"):
    return CapacityRow(project_id=project_id, project_name=project_name, tier=tier, stage=stage, status=status)


# --- compute_capacity ---


def test_empty_capacity_zero(cfg):
    assert compute_capacity([], cfg) == 0.0


def test_one_t3_building_on_track(cfg):
    rows = [_row("Tier 3", "building", "ON_TRACK")]
    assert compute_capacity(rows, cfg) == pytest.approx(1.0)


def test_two_t3_building_on_track_at_cap(cfg):
    rows = [_row("Tier 3", "building", "ON_TRACK", "p1"), _row("Tier 3", "building", "ON_TRACK", "p2")]
    assert compute_capacity(rows, cfg) == pytest.approx(2.0)


def test_two_t2_building_partial(cfg):
    rows = [_row("Tier 2", "building", "ON_TRACK", "p1"), _row("Tier 2", "stabilisation_delivery", "ON_TRACK", "p2")]
    assert compute_capacity(rows, cfg) == pytest.approx(1.34, abs=0.01)


def test_t3_building_at_risk_doubles(cfg):
    rows = [_row("Tier 3", "building", "AT_RISK")]
    assert compute_capacity(rows, cfg) == pytest.approx(2.0)


def test_t4_building_on_track(cfg):
    rows = [_row("Tier 4", "building", "ON_TRACK")]
    assert compute_capacity(rows, cfg) == pytest.approx(2.0)


def test_t3_close_out_on_track_zero(cfg):
    rows = [_row("Tier 3", "close_out_retrospective", "ON_TRACK")]
    assert compute_capacity(rows, cfg) == pytest.approx(0.0)


def test_scoping_zero_any_status(cfg):
    rows = [_row("Tier 4", "scoping_solution_design", "BLOCKED_INTERNAL")]
    assert compute_capacity(rows, cfg) == pytest.approx(0.0)


# --- classify_band ---


def test_band_free_strict_lt_one(cfg):
    assert classify_band(0.99, cfg) == Band.FREE


def test_band_partial_at_one(cfg):
    """Boundary: 1.0 -> PARTIAL (strict free_below)."""
    assert classify_band(1.0, cfg) == Band.PARTIAL


def test_band_partial_at_one_ninety_nine(cfg):
    assert classify_band(1.99, cfg) == Band.PARTIAL


def test_band_at_cap_at_two(cfg):
    assert classify_band(2.0, cfg) == Band.AT_CAP


# --- assess (full integration) ---


def test_assess_eligible_for_new_t3(cfg):
    rows = [_row("Tier 3", "building", "ON_TRACK")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.capacity_used == pytest.approx(1.0)
    assert v.band == Band.PARTIAL
    assert v.eligible_for_new is True
    assert v.ineligible_reason == IneligibleReason.OK


def test_assess_capacity_overflow(cfg):
    rows = [_row("Tier 3", "building", "ON_TRACK", "p1"), _row("Tier 3", "building", "ON_TRACK", "p2")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is False
    assert v.ineligible_reason == IneligibleReason.CAPACITY_OVERFLOW


def test_assess_max_projects_cap_uliumdzhi(cfg):
    """4 scoping projects => capacity 0 but eligible=False via hard rule."""
    rows = [_row("Tier 3", "scoping_solution_design", "BLOCKED_INTERNAL", f"p{i}") for i in range(4)]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.capacity_used == pytest.approx(0.0)
    assert v.total_projects == 4
    assert v.eligible_for_new is False
    assert v.ineligible_reason == IneligibleReason.MAX_PROJECTS_CAP


def test_assess_pto_today_blocks(cfg):
    v = assess([], on_pto_today=True, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is False
    assert v.ineligible_reason == IneligibleReason.ON_PTO_TODAY


def test_assess_hard_exclude_blocks(cfg):
    v = assess([], on_pto_today=False, pto_upcoming=None, in_hard_exclude=True, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is False
    assert v.ineligible_reason == IneligibleReason.IN_HARD_EXCLUDE


def test_assess_pto_upcoming_does_not_block(cfg):
    v = assess([], on_pto_today=False, pto_upcoming=("2026-05-15", "2026-05-22"), in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is True
    assert v.pto_upcoming_dates == ("2026-05-15", "2026-05-22")


def test_assess_capacity_at_one_plus_t3_eligible(cfg):
    """Boundary: 1.0 + 1.0 = 2.0 == cap, still eligible."""
    rows = [_row("Tier 3", "building", "ON_TRACK")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is True


def test_assess_capacity_at_one_thirty_four_plus_t3_overflow(cfg):
    """1.34 + 1.0 = 2.34 > 2.0 -> not eligible."""
    rows = [_row("Tier 2", "building", "ON_TRACK", "p1"), _row("Tier 2", "stabilisation_delivery", "ON_TRACK", "p2")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.eligible_for_new is False
    assert v.ineligible_reason == IneligibleReason.CAPACITY_OVERFLOW


# --- soft signal ---


def test_soft_all_scoping(cfg):
    rows = [_row("Tier 3", "scoping_solution_design", "BLOCKED_INTERNAL", f"p{i}") for i in range(2)]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.is_soft is True
    assert SoftReason.ALL_SCOPING_OR_DISCOVERY in v.soft_reasons


def test_soft_all_close_out(cfg):
    rows = [_row("Tier 3", "close_out_retrospective", "ON_TRACK", "p1"), _row("Tier 2", "close_out_retrospective", "ON_TRACK", "p2")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.is_soft is True
    assert SoftReason.ALL_CLOSE_OUT_ON_TRACK in v.soft_reasons


def test_not_soft_active_building(cfg):
    rows = [_row("Tier 3", "building", "ON_TRACK")]
    v = assess(rows, on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=1.0, cfg=cfg)
    assert v.is_soft is False


def test_empty_not_soft(cfg):
    """0 projects -> not SOFT (truly empty, not winding down)."""
    v = assess([], on_pto_today=False, pto_upcoming=None, in_hard_exclude=False, new_project_weight=0.0, cfg=cfg)
    assert v.is_soft is False
    assert v.band == Band.FREE
