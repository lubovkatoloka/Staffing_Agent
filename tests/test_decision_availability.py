import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import AvailabilityLabel, classify_availability
from staffing_agent.decision.availability import soft_assignment_match


@pytest.fixture
def cfg() -> dict:
    return load_decision_config()


def test_free_below_50_percent(cfg: dict) -> None:
    a = classify_availability(0.49, active_project_count=2, decision_cfg=cfg)
    assert a.label == AvailabilityLabel.FREE


def test_partial_band(cfg: dict) -> None:
    a = classify_availability(0.5, active_project_count=2, decision_cfg=cfg)
    assert a.label == AvailabilityLabel.PARTIAL
    a2 = classify_availability(0.79, active_project_count=2, decision_cfg=cfg)
    assert a2.label == AvailabilityLabel.PARTIAL


def test_busy_from_80(cfg: dict) -> None:
    a = classify_availability(0.8, active_project_count=2, decision_cfg=cfg)
    assert a.label == AvailabilityLabel.BUSY


def test_unverified_zero_occ_zero_projects(cfg: dict) -> None:
    a = classify_availability(0.0, active_project_count=0, decision_cfg=cfg)
    assert a.label == AvailabilityLabel.UNVERIFIED


def test_not_unverified_when_projects_positive(cfg: dict) -> None:
    a = classify_availability(0.0, active_project_count=1, decision_cfg=cfg)
    assert a.label == AvailabilityLabel.FREE


def test_pto_full_week_priority(cfg: dict) -> None:
    a = classify_availability(
        0.2,
        active_project_count=3,
        pto_full_week=True,
        decision_cfg=cfg,
    )
    assert a.label == AvailabilityLabel.PTO


def test_soft_overrides_band(cfg: dict) -> None:
    a = classify_availability(
        0.2,
        active_project_count=1,
        has_soft_assignment=True,
        decision_cfg=cfg,
    )
    assert a.label == AvailabilityLabel.SOFT


def test_soft_match_discovery_stage(cfg: dict) -> None:
    assert soft_assignment_match(stage="discovery", status="ON_TRACK", decision_cfg=cfg) is True


def test_soft_match_blocked_status(cfg: dict) -> None:
    assert soft_assignment_match(stage="building", status="BLOCKED_CLIENT", decision_cfg=cfg) is True


def test_soft_no_match(cfg: dict) -> None:
    assert soft_assignment_match(stage="building", status="ON_TRACK", decision_cfg=cfg) is False
