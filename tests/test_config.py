from staffing_agent.config_loader import (
    load_decision_config,
    load_thresholds,
    load_tier_classification_prompt,
)


def test_decision_config_load() -> None:
    cfg = load_decision_config()
    assert cfg["spec_version"] == "1.0"
    assert "notion.so" in cfg.get("notion_spec_url", "")
    assert cfg["occupation"]["free_below"] == 0.5
    assert "staffing_ps_gates" in cfg
    assert cfg["occupation"]["partial_below"] == 0.8


def test_load_thresholds_alias() -> None:
    assert load_thresholds() == load_decision_config()


def test_tier_classification_prompt_has_v2_sections() -> None:
    tc = load_tier_classification_prompt()
    assert tc.get("framework_url")
    assert "system_boundary" in tc
    assert "Step 0" in (tc.get("classification_rules") or "")
    assert "thread_kind" in (tc.get("output_requirements") or "")
    assert "SCQA" in (tc.get("framework_alignment") or "")
