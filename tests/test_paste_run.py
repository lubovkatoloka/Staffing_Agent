import pytest

from staffing_agent.paste_run import build_reply_from_paste


def test_build_reply_from_paste_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply, src = build_reply_from_paste("Need a DPM for Tier 2 next week.")
    assert src == "mock"
    assert "Phase B" in reply
    assert "Phase C" in reply
    assert "Staffing Agent — context" in reply
