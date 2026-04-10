from staffing_agent.config_loader import load_thresholds


def test_thresholds_load() -> None:
    th = load_thresholds()
    assert th["spec_version"] == "1.0"
    assert th["occupation"]["free_below"] == 0.5
