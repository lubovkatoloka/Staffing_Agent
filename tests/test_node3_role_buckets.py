from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import CapacityRow, assess
from staffing_agent.node3_role_buckets import format_role_bucket_section


def _row(cfg, user_name: str, project_role: str, *projects: CapacityRow) -> dict:
    v = assess(
        list(projects),
        on_pto_today=False,
        pto_upcoming=None,
        in_hard_exclude=False,
        new_project_weight=0.0,
        cfg=cfg,
    )
    return {
        "user_name": user_name,
        "project_role": project_role,
        "_capacity_verdict": v,
        "_capacity_rows": tuple(projects),
    }


def test_role_buckets_basic():
    cfg = load_decision_config()
    rows = [
        _row(cfg, "Alice", "soe", CapacityRow("p1", "P1", "Tier 3", "building", "ON_TRACK")),
        _row(cfg, "Bob", "dpm", CapacityRow("p2", "P2", "Tier 3", "building", "AT_RISK")),
        _row(cfg, "Carol", "wfm", CapacityRow("p3", "P3", "Tier 2", "building", "ON_TRACK")),
    ]
    text = format_role_bucket_section(rows, decision_cfg=cfg)
    assert "SO" in text
    assert "Alice" in text
    assert "DPM" in text
    assert "Bob" in text
    assert "WFM" in text
    assert "Carol" in text


def test_role_buckets_tier2_hides_wfm():
    cfg = load_decision_config()
    rows = [
        _row(cfg, "Alice", "soe", CapacityRow("p1", "P1", "Tier 3", "building", "ON_TRACK")),
        _row(cfg, "Bob", "dpm", CapacityRow("p2", "P2", "Tier 3", "building", "ON_TRACK")),
        _row(cfg, "Carol", "wfm", CapacityRow("p3", "P3", "Tier 2", "building", "ON_TRACK")),
    ]
    text = format_role_bucket_section(rows, decision_cfg=cfg, tier=2)
    assert "Node 2" in text
    assert "Carol" not in text
    assert "WFM / WFC" not in text

