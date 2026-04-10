import pytest

from staffing_agent.extraction import extract_request_spec, uses_mock_llm


def test_extraction_mock_when_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec, src = extract_request_spec("Need a DPM for a Tier 2 pipeline project next week.")
    assert src == "mock"
    assert spec.notes == "mock_llm"


def test_uses_mock_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    assert uses_mock_llm() is True
