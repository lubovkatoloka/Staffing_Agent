import pytest

from staffing_agent.node3_occupation import node3_slack_markdown


def test_node3_without_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_PROFILE", raising=False)
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "full")
    text = node3_slack_markdown(tier=2)
    assert "Node 3" in text
    assert "DATABRICKS_PROFILE" in text
    assert "Node 4" in text
    assert "Tier 2" in text


def test_node3_minimal_without_profile_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_PROFILE", raising=False)
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    text = node3_slack_markdown(tier=2)
    assert "Node 3" not in text
    assert "DATABRICKS_PROFILE" in text
