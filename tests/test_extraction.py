import pytest

from staffing_agent.extraction import (
    LLM_ACTIONABLE_TIER_CONFIDENCE,
    _normalize_llm_spec_dict,
    apply_llm_tier_confidence_gate,
    apply_narrow_staffing_thread_fallback,
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


def test_extraction_llm_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec, src = extract_request_spec("Need a DPM for a Tier 2 pipeline project next week.")
    assert src == "llm_unavailable"
    assert "ANTHROPIC_API_KEY" in spec.notes


def test_extraction_llm_unavailable_deal_thread_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Shopify — Mobile App Testing\n"
        "Deal value ($k): US$120.00\n"
    )
    spec, src = extract_request_spec(thread)
    assert src == "llm_unavailable"
    assert spec.thread_kind == "deal_notification"


def test_apply_llm_tier_confidence_gate_clears_low_confidence() -> None:
    spec = RequestSpec(tier=3, complexity_class="M", summary="x", confidence=0.69)
    out = apply_llm_tier_confidence_gate(spec)
    assert out.tier is None
    assert out.complexity_class is None
    assert out.sese_path is False
    assert str(LLM_ACTIONABLE_TIER_CONFIDENCE) in out.notes or "0.7" in out.notes


def test_apply_llm_tier_confidence_gate_keeps_at_threshold() -> None:
    spec = RequestSpec(tier=2, complexity_class="S", summary="x", confidence=0.7)
    out = apply_llm_tier_confidence_gate(spec)
    assert out.tier == 2
    assert out.complexity_class == "S"


def test_extract_anthropic_success_low_confidence_clears_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _low_conf(**_kw: object) -> dict:
        return {
            "thread_kind": "staffing_request",
            "tier": 3,
            "complexity_class": "M",
            "tier_rationale": "Because size only",
            "summary": "Thread",
            "confidence": 0.55,
            "judge": "Co · deal · ten people",
            "project_type_tags": [],
            "notes": "",
        }

    monkeypatch.setattr("staffing_agent.anthropic_llm.complete_json", _low_conf)
    spec, src = extract_request_spec("Need ten FTE for this account; staff it.")
    assert src == "anthropic"
    assert spec.tier is None
    assert "0.7" in spec.notes or "confidence" in spec.notes.lower()


def test_extract_anthropic_success_high_confidence_keeps_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAFFING_AGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _high(**_kw: object) -> dict:
        return {
            "thread_kind": "staffing_request",
            "tier": 3,
            "complexity_class": "M",
            "tier_rationale": "Multi-app pilot, domain evals",
            "summary": "Thread",
            "confidence": 0.85,
            "judge": "Acme · pilot · multi-app",
            "project_type_tags": ["Evals"],
            "notes": "",
        }

    monkeypatch.setattr("staffing_agent.anthropic_llm.complete_json", _high)
    spec, src = extract_request_spec("RL gym style pilot with 12 apps and eval matrix.")
    assert src == "anthropic"
    assert spec.tier == 3
    assert spec.complexity_class == "M"


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


def test_deal_feed_fallback_with_who_is_available_stays_tier_null(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert spec.tier is None
    assert spec.complexity_class is None


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


def test_normalize_llm_spec_dict_attio_string_fields() -> None:
    long_val = "x" * 3000
    d = _normalize_llm_spec_dict(
        {
            "tier": 2,
            "summary": "ok",
            "request_type": " expansion ",
            "attio_deal_name": long_val,
            "attio_company_name": None,
        }
    )
    spec = RequestSpec.model_validate(d)
    assert spec.request_type == "expansion"
    assert len(spec.attio_deal_name) == 2000
    assert spec.attio_company_name == ""


def test_normalize_llm_spec_dict_narrow_fields() -> None:
    d = _normalize_llm_spec_dict(
        {
            "narrow_staffing_scenario": "call_support",
            "parsed_ask_summary_en": " Who covers the call? ",
            "include_full_team_candidates": "yes",
            "call_support_role_tags": ["dpm", "SSOE_SOE"],
            "narrow_single_role": "SoE",
        }
    )
    spec = RequestSpec.model_validate(d)
    assert spec.narrow_staffing_scenario == "call_support"
    assert spec.parsed_ask_summary_en.startswith("Who covers")
    assert spec.include_full_team_candidates is True
    assert spec.call_support_role_tags == ["dpm", "SSOE_SOE"]
    assert spec.narrow_single_role == "soe"


def test_apply_narrow_staffing_thread_fallback_single_role_with_tier() -> None:
    spec = RequestSpec(tier=3, complexity_class="M", summary="x")
    out = apply_narrow_staffing_thread_fallback(
        "need 1 SOE tier 3 or tier 3 experience, coding", spec
    )
    assert out.narrow_staffing_scenario == "single_role"
    assert out.narrow_single_role == "soe"
    assert "shortlist" in (out.parsed_ask_summary_en or "").lower()


def test_apply_narrow_staffing_thread_fallback_skips_when_full_team_hint() -> None:
    spec = RequestSpec(tier=3, complexity_class="M", summary="x")
    out = apply_narrow_staffing_thread_fallback(
        "need 1 SOE tier 3 and a full team for scale", spec
    )
    assert out.narrow_staffing_scenario is None


def test_apply_narrow_staffing_thread_fallback_call_support() -> None:
    spec = RequestSpec(tier=None, summary="x")
    out = apply_narrow_staffing_thread_fallback(
        "Need staffing for tomorrow.\nWho covers the client call?\nDeal value ($k): US$100.00",
        spec,
    )
    assert out.narrow_staffing_scenario == "call_support"
    assert out.call_support_role_tags


def test_mock_llm_applies_narrow_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec, src = extract_request_spec("Need a DPM for Tier 2 pipeline next week.")
    assert src == "mock"
    assert spec.narrow_staffing_scenario == "single_role"
    assert spec.narrow_single_role == "dpm"


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
