from staffing_agent.config_loader import load_decision_config
from staffing_agent.node3_role_buckets import format_role_bucket_section


def test_role_buckets_basic():
    cfg = load_decision_config()
    rows = [
        {
            "user_name": "Alice",
            "project_role": "soe",
            "occupation": 0.3,
        },
        {
            "user_name": "Bob",
            "project_role": "dpm",
            "occupation": 0.4,
        },
        {
            "user_name": "Carol",
            "project_role": "wfm",
            "occupation": 0.2,
        },
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
        {
            "user_name": "Alice",
            "project_role": "soe",
            "occupation": 0.3,
        },
        {
            "user_name": "Bob",
            "project_role": "dpm",
            "occupation": 0.4,
        },
        {
            "user_name": "Carol",
            "project_role": "wfm",
            "occupation": 0.2,
        },
    ]
    text = format_role_bucket_section(rows, decision_cfg=cfg, tier=2)
    assert "Node 2" in text
    assert "Carol" not in text
    assert "WFM / WFC" not in text
