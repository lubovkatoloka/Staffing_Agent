import pytest

from staffing_agent.extraction import (
    _normalize_llm_spec_dict,
    apply_deal_feed_availability_tier_hint,
    extract_request_spec,
    explicit_tier_in_thread,
    uses_mock_llm,
)
from staffing_agent.models.request_spec import RequestSpec


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


def test_apply_deal_feed_availability_tier_hint_fills_tier3() -> None:
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Shopify — Mobile App Testing\n"
        "Deal value ($k): US$120.00\n"
        "Liuba: scope text…\n"
        "<@U123>: who_is_available\n"
    )
    spec = RequestSpec(
        thread_kind="deal_notification",
        tier=None,
        complexity_class=None,
        tier_rationale="",
        project_type_tags=[],
        summary="x",
        confidence=0.2,
        notes="",
    )
    out = apply_deal_feed_availability_tier_hint(thread, spec)
    assert out.tier == 3
    assert out.complexity_class == "M"
    assert "availability ping" in out.tier_rationale.lower()


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


def test_deal_feed_fallback_with_who_is_available_gets_tier_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(**_kw: object) -> dict:
        raise ValueError("simulated API failure")

    monkeypatch.setattr("staffing_agent.anthropic_llm.complete_json", _boom)
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Shopify — Mobile App Testing\n"
        "Deal value ($k): US$120.00\n"
        "Thread in deals-new\n"
        "<@U123>: who_is_available\n"
    )
    spec, src = extract_request_spec(thread)
    assert src == "anthropic_fallback"
    assert spec.tier == 3
    assert spec.complexity_class == "M"


def test_explicit_tier_in_thread() -> None:
    assert explicit_tier_in_thread("need 1 SOE tier 3 or tier 3 experience, coding") == 3
    assert explicit_tier_in_thread("Tier 2 pipeline") == 2


def test_normalize_llm_spec_dict_coerces_tier_and_confidence() -> None:
    d = _normalize_llm_spec_dict(
        {"tier": "Tier 3", "confidence": 1.7, "project_type_tags": "Evals", "complexity_class": "m"}
    )
    spec = RequestSpec.model_validate(d)
    assert spec.tier == 3
    assert spec.confidence == 1.0
    assert spec.project_type_tags == ["Evals"]
    assert spec.complexity_class == "M"


def test_extraction_rescue_when_phase_b_fails_but_tier_in_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slack screenshot case: explicit tier 3 + SOE need — must not end with tier=None only."""
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(**_kw: object) -> dict:
        raise ValueError("simulated JSON/API failure")

    monkeypatch.setattr("staffing_agent.anthropic_llm.complete_json", _boom)
    thread = "need 1 SOE tier 3 or tier 3 experience, coding @who_is_available"
    spec, src = extract_request_spec(thread)
    assert src == "anthropic_rescue"
    assert spec.tier == 3
    assert spec.complexity_class == "M"
    assert spec.thread_kind == "staffing_request"
    assert "Coding" in spec.project_type_tags
    assert "rescue" in spec.tier_rationale.lower() or "Heuristic" in spec.tier_rationale


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
