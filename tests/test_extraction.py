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


def test_deal_feed_fallback_when_anthropic_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """If JSON/LLM fails but thread matches Attio/deal heuristics, return deal_notification + brief."""
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(**_kw: object) -> dict:
        raise ValueError("simulated API failure")

    monkeypatch.setattr("staffing_agent.anthropic_llm.complete_json", _boom)
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Amazon Q — Dataset\n"
        "Deal value ($k): US$300.00\n"
        "Client: Amazon\n"
        "Exploring requirements.\n"
    )
    spec, src = extract_request_spec(thread)
    assert src == "anthropic_fallback"
    assert spec.thread_kind == "deal_notification"
    assert spec.tier is None
    assert "Amazon" in spec.summary or "Dataset" in spec.summary
    assert "simulated" in spec.notes or "Phase B error" in spec.notes


def test_staffing_force_tier_overrides_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("STAFFING_FORCE_TIER", "3")
    spec, src = extract_request_spec("anything")
    assert src == "mock"
    assert spec.tier == 3
    assert spec.complexity_class == "M"
    assert "STAFFING_FORCE_TIER=3" in spec.tier_rationale
    assert "tier overridden" in spec.notes
