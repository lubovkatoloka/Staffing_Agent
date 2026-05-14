import pytest

from staffing_agent.paste_run import build_reply_from_paste


def test_build_reply_from_paste_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "full")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reply, src = build_reply_from_paste("Need a DPM for Tier 2 next week.")
    assert src == "mock"
    assert "📌" in reply
    assert "Phase C" in reply or "➡️" in reply
    assert "Staffing Agent — context" in reply
    assert "Node 2 — candidate pool" in reply
    assert "```json" in reply
    assert "RequestSpec" in reply or "narrow_staffing_scenario" in reply


def test_team_capacity_routes_to_live_capacity_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    from staffing_agent.models.request_spec import RequestSpec
    from staffing_agent.paste_run import build_slack_mention_reply

    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    calls: list[str] = []

    def _cap(*, only_role: object = None, timeout_sec: int = 300) -> list[str]:
        calls.append(str(only_role))
        return ["CAPACITY_SNAPSHOT_BODY"]

    monkeypatch.setattr("staffing_agent.paste_run.build_live_capacity_markdown", _cap)
    spec = RequestSpec(tier=None, summary="capacity ask")
    chunks = build_slack_mention_reply(
        [{"user": "U1", "text": "Team capacity @bot"}],
        [],
        spec,
        extraction_src_label="anthropic",
        thread_plain="Team capacity @who_is_available",
    )
    assert calls == ["None"]
    assert any("CAPACITY_SNAPSHOT_BODY" in c for c in chunks)


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
    chunks = build_slack_mention_reply([], [], spec, extraction_src_label="anthropic")
    text = chunks[0]
    assert not calls
    assert "capacity" in text.lower() or "context" in text.lower()


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
    assert "Context:" not in reply
    assert "```json" not in reply
    assert "Recommendation" in reply or "capacity" in reply.lower()


def test_narrow_pre_sales_routes_before_team_capacity_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM narrow scenario wins over substring 'team / capacity' in the same thread."""
    from staffing_agent.models.request_spec import RequestSpec
    from staffing_agent.paste_run import build_slack_mention_reply

    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    cap_calls: list[dict[str, object]] = []

    def _track_cap(**kwargs: object) -> list[str]:
        cap_calls.append(dict(kwargs))
        return ["NARROW_BLOCK"]

    monkeypatch.setattr("staffing_agent.paste_run.build_live_capacity_markdown", _track_cap)
    spec = RequestSpec(
        tier=None,
        summary="deal + RFP",
        narrow_staffing_scenario="pre_sales_shape",
        parsed_ask_summary_en="Shape the RFP; need SO coverage.",
    )
    chunks = build_slack_mention_reply(
        [{"user": "U1", "text": "x"}],
        [],
        spec,
        extraction_src_label="anthropic",
        thread_plain="Team capacity mention\npre-sales RFP for Acme",
    )
    assert len(cap_calls) == 1
    assert cap_calls[0].get("only_role") == "so"
    assert "Pre-sales" in str(cap_calls[0].get("role_shortlist_title"))
    assert any("NARROW_BLOCK" in c for c in chunks)
    assert any("Shape the RFP" in c for c in chunks)
