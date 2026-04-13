"""Phase C Slack footer: decision demo + Databricks hints (no live CLI in CI)."""

import os

from staffing_agent.slack_phase_c import build_phase_c_section


def test_phase_c_contains_demo_and_hint(monkeypatch):
    monkeypatch.delenv("DATABRICKS_PROFILE", raising=False)
    monkeypatch.delenv("STAFFING_AGENT_SLACK_DBX_SMOKE", raising=False)
    text = build_phase_c_section()
    assert "Phase C" in text
    assert "PARTIAL" in text or "partial" in text.lower()
    assert "DATABRICKS_PROFILE" in text


def test_phase_c_with_profile_suggests_smoke_flag(monkeypatch):
    monkeypatch.setenv("DATABRICKS_PROFILE", "test-profile")
    monkeypatch.delenv("STAFFING_AGENT_SLACK_DBX_SMOKE", raising=False)
    text = build_phase_c_section()
    assert "STAFFING_AGENT_SLACK_DBX_SMOKE" in text
    assert "check-dbx" in text


def test_phase_c_smoke_when_enabled(monkeypatch):
    monkeypatch.setenv("DATABRICKS_PROFILE", "p")
    monkeypatch.setenv("STAFFING_AGENT_SLACK_DBX_SMOKE", "1")

    def fake_run(_sql: str):
        return True, "ok_row"

    monkeypatch.setattr("staffing_agent.slack_phase_c.run_sql_query", fake_run)
    text = build_phase_c_section()
    assert "Databricks smoke" in text
    assert "ok_row" in text
