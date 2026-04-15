"""Rules from staffing_ps_gates + project snapshot rows."""

from staffing_agent.config_loader import load_decision_config
from staffing_agent.project_staffing_gates import project_staffing_gate_reason


def _cfg():
    return load_decision_config()


def test_only_discovery_overrides_heavy_rules() -> None:
    rows = [
        {"stage": "discovery", "status": "ON_TRACK", "dpm": "Alice A"},
    ]
    assert project_staffing_gate_reason(rows, tier=2, decision_cfg=_cfg()) is None


def test_three_heavy_blocks_tier_2() -> None:
    rows = [
        {"stage": "building", "status": "ON_TRACK", "dpm": "Bob B"},
        {"stage": "stabilisation_delivery", "status": "BEHIND", "dpm": "Bob B"},
        {"stage": "building", "status": "AT_RISK", "dpm": "Bob B"},
    ]
    assert project_staffing_gate_reason(rows, tier=2, decision_cfg=_cfg()) == "ps_three_plus_heavy_low_tier"


def test_three_orders_one_blocked_scoping_only() -> None:
    """3+ orders, 1 blocked, heavy count < 3 — footnote path (not all light-only stages)."""
    rows = [
        {"stage": "close_out_retrospective", "status": "ON_TRACK", "dpm": "C C"},
        {"stage": "close_out_retrospective", "status": "ON_TRACK", "dpm": "C C"},
        {"stage": "scoping_solution_design", "status": "BLOCKED_CLIENT", "dpm": "C C"},
    ]
    assert project_staffing_gate_reason(rows, tier=3, decision_cfg=_cfg()) == "ps_scoping_discovery_only"


def test_three_heavy_plus_blocked_still_blocks_not_scoping_only() -> None:
    """3+ building/stab projects: blocked-by-client on one order does not downgrade to scoping-only."""
    rows = [
        {"stage": "building", "status": "ON_TRACK", "dpm": "C C"},
        {"stage": "building", "status": "ON_TRACK", "dpm": "C C"},
        {"stage": "building", "status": "BLOCKED_CLIENT", "dpm": "C C"},
    ]
    assert project_staffing_gate_reason(rows, tier=2, decision_cfg=_cfg()) == "ps_three_plus_heavy_low_tier"


def test_single_building_non_blocked_blocks() -> None:
    rows = [
        {"stage": "building", "status": "ON_TRACK", "dpm": "D D"},
    ]
    assert project_staffing_gate_reason(rows, tier=2, decision_cfg=_cfg()) == "ps_active_building"


def test_deadline_this_week_overrides() -> None:
    from datetime import date, timedelta

    today = date.today()
    rows = [
        {"stage": "building", "status": "ON_TRACK", "dpm": "E E", "deadline": today.isoformat()},
    ]
    assert project_staffing_gate_reason(rows, tier=2, decision_cfg=_cfg()) is None
