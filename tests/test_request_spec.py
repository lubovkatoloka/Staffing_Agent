import pytest
from pydantic import ValidationError

from staffing_agent.models.request_spec import RequestSpec


def test_tier_validation() -> None:
    RequestSpec(tier=3, summary="x")
    with pytest.raises(ValidationError):
        RequestSpec(tier=5, summary="x")


def test_slack_brief_no_json() -> None:
    s = RequestSpec(
        tier=2,
        summary="TTS eval intro call.",
        project_type_tags=["TTS", "Evals"],
        complexity_class="S",
    )
    b = s.to_slack_brief()
    assert "Tier 2" in b
    assert "TTS" in b
    assert "TTS eval intro call." in b
    assert "```" not in b


def test_slack_block_contains_summary() -> None:
    s = RequestSpec(
        tier=2,
        summary="hello",
        confidence=0.5,
        complexity_class="S",
        tier_rationale="Standard pipeline.",
    )
    blk = s.to_slack_block()
    assert "hello" in blk
    assert '"tier": 2' in blk
    assert "tier_rationale" in blk
