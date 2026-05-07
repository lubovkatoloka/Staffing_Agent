import pytest

from staffing_agent.paste_run import build_reply_from_paste


def test_build_reply_from_paste_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "full")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply, src = build_reply_from_paste("Need a DPM for Tier 2 next week.")
    assert src == "mock"
    assert "Phase B" in reply
    assert "Phase C" in reply
    assert "Staffing Agent — context" in reply


def test_team_capacity_routes_to_live_capacity_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    from staffing_agent.models.request_spec import RequestSpec
    from staffing_agent.paste_run import build_slack_mention_reply

    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    calls: list[str] = []

    def _cap(*, only_role: object = None, timeout_sec: int = 300) -> str:
        calls.append(str(only_role))
        return "CAPACITY_SNAPSHOT_BODY"

    monkeypatch.setattr("staffing_agent.paste_run.build_live_capacity_markdown", _cap)
    spec = RequestSpec(tier=None, summary="capacity ask")
    text = build_slack_mention_reply(
        [{"user": "U1", "text": "Team capacity @bot"}],
        [],
        spec,
        extraction_src_label="anthropic",
        thread_plain="Team capacity @who_is_available",
    )
    assert calls == ["None"]
    assert "CAPACITY_SNAPSHOT_BODY" in text


def test_minimal_reply_without_tier_does_not_call_node3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off-topic threads: no Databricks node3; static Tier-required message instead."""
    from staffing_agent.models.request_spec import RequestSpec
    from staffing_agent.paste_run import build_slack_mention_reply

    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    calls: list[object] = []

    def _should_not_run(**_kw: object) -> str:
        calls.append(True)
        return "node3 should not run"

    monkeypatch.setattr("staffing_agent.paste_run.node3_slack_markdown", _should_not_run)
    spec = RequestSpec(tier=None, summary="A Google Doc about apps; not a staffing request.")
    text = build_slack_mention_reply([], [], spec, extraction_src_label="anthropic")
    assert not calls
    assert "контекст" in text or "Team capacity" in text


def test_attio_style_thread_minimal_has_no_internal_preamble(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Amazon Q — Dataset\n"
        "Deal value ($k): US$300.00\n"
        "Exploring requirements.\n"
    )
    reply, src = build_reply_from_paste(thread)
    assert src == "mock"
    assert "Deal-feed context" not in reply
    assert "Context:" not in reply


def test_build_reply_from_paste_minimal_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply, src = build_reply_from_paste("Need a DPM for Tier 2 next week.")
    assert src == "mock"
    assert "Staffing Agent — context" not in reply
    assert "Phase B" not in reply
    assert "Context:" not in reply
    assert "Recommendation" in reply or "capacity" in reply.lower()
