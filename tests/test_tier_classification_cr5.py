"""Regression: CR-5 tier prompt YAML (line budget, 6-dimension rubric, anti-size)."""

from __future__ import annotations

from pathlib import Path

from staffing_agent.config_loader import load_tier_classification_prompt


def test_tier_classification_yaml_line_budget() -> None:
    path = Path(__file__).resolve().parents[1] / "config" / "tier_classification.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 90, f"expected ≤90 lines, got {len(lines)}"


def test_tier_classification_yaml_six_dimensions_and_anti_size() -> None:
    raw = Path(__file__).resolve().parents[1] / "config" / "tier_classification.yaml"
    text = raw.read_text(encoding="utf-8").lower()
    for needle in (
        "**pipeline**",
        "qc / automation",
        "**expertise**",
        "**commercial**",
        "**infra / platform**",
        "**ownership**",
    ):
        assert needle.lower() in text
    for needle in ("anti-size", "fte", "headcount", "team size"):
        assert needle in text
    assert "0.7" in text


def test_tier_classification_prompt_loads() -> None:
    tc = load_tier_classification_prompt()
    assert tc.get("framework_url")
    cr = tc.get("classification_rules") or ""
    assert "Step 0" in cr
    assert "Anti-size" in (tc.get("framework_alignment") or "")
