from staffing_agent.config_loader import load_decision_config, load_thresholds


def test_decision_config_load() -> None:
    cfg = load_decision_config()
    assert cfg["spec_version"] == "1.0"
    assert "notion.so" in cfg.get("notion_spec_url", "")
    assert cfg["occupation"]["free_below"] == 0.5
    assert cfg["occupation"]["partial_below"] == 0.8


def test_load_thresholds_alias() -> None:
    assert load_thresholds() == load_decision_config()
