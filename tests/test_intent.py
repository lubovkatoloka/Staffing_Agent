import pytest

from staffing_agent.intent import (
    is_bare_slack_capacity_mention_trigger,
    is_likely_deal_notification_thread,
    is_team_capacity_query,
    multi_roles_from_thread,
    only_role_from_thread,
    single_role_focus_from_thread,
    slack_trigger_visible_text,
    thread_has_availability_capacity_ping,
    thread_suggests_full_team_intent,
    thread_suggests_pre_sales_rfp_deal_shape,
)


def test_team_capacity_phrases() -> None:
    assert is_team_capacity_query("Team capacity @who_is_available")
    assert is_team_capacity_query("кто свободен на неделе")
    assert is_team_capacity_query("who is available for a call")


def test_single_role_focus_need_soe_tier3() -> None:
    assert (
        single_role_focus_from_thread("need 1 SOE tier 3 or tier 3 experience, coding") == "soe"
    )
    assert single_role_focus_from_thread("Looking for a DPM for next sprint") == "dpm"


def test_single_role_focus_none_when_team_capacity() -> None:
    assert single_role_focus_from_thread("Team capacity @who_is_available") is None


def test_thread_has_availability_capacity_ping() -> None:
    """Underscore bot handle normalizes to 'who is available' for tier-hint pairing."""
    assert thread_has_availability_capacity_ping("deals-new\n<@U123>: who_is_available")
    assert thread_has_availability_capacity_ping("Please check who is available for Shopify")
    assert thread_has_availability_capacity_ping("Team capacity snapshot for Q2")
    assert not thread_has_availability_capacity_ping("APP:attio: New deal\nDeal value: 100\nno ping here")


def test_deal_feed_heuristic() -> None:
    assert is_likely_deal_notification_thread(
        "APP:attio: New deal created\nAmazon Q — Dataset\nDeal value ($k): US$300"
    )
    assert is_likely_deal_notification_thread(
        "Thread in deals-new | Apr 13th | View message\nClient: Amazon"
    )
    assert is_likely_deal_notification_thread("Deal\u00a0value ($k): US$300\nClient: Amazon")
    assert not is_likely_deal_notification_thread("random chat about lunch")


def test_bot_handle_with_underscores_matches_who_is_available() -> None:
    """Slack shows @who_is_available without spaces — still team capacity intent."""
    assert is_team_capacity_query("@who_is_available")
    assert is_team_capacity_query("who_is_available")
    assert is_team_capacity_query("deals thread\nwho_is_available")


def test_not_capacity_project_thread() -> None:
    assert not is_team_capacity_query("Need a DPM for Tier 2 TTS evals next week.")


def test_bare_app_mention_trigger_is_team_capacity() -> None:
    """Slack often sends only <@U…> with no ‘who is available’ string in text."""
    assert is_bare_slack_capacity_mention_trigger("<@U09ABCDEF>")
    assert is_bare_slack_capacity_mention_trigger("  <@W01234567>  ")
    assert slack_trigger_visible_text("<@U09> <!here>") == ""
    assert not is_bare_slack_capacity_mention_trigger("<@U09> need a DPM for Tier 2")

    deal_thread = (
        "Attio New deal created\nAmazon Q — Dataset\nDeal value ($k): US$300\n"
        "Exploring requirements and client quote."
    )
    # Rich deal thread: bare @bot must NOT short-circuit to generic team capacity (Phase B needs full context).
    assert not is_team_capacity_query(deal_thread, trigger_message_text="<@U09ABCDEF>")
    assert not is_team_capacity_query(deal_thread, trigger_message_text="<@U09> staff Tier 3")

    # No deal-feed signals: bare ping still means “who’s free” snapshot.
    assert is_team_capacity_query("Quick question in #general", trigger_message_text="<@U09ABCDEF>")


def test_deal_thread_bot_handle_must_not_trigger_team_capacity() -> None:
    """
    Slack app name ``who_is_available`` normalizes to the substring "who is available" — that is not
    a user-authored capacity ask; deal threads must go to Phase B unless they say e.g. team capacity.
    """
    thread = (
        "APP:attio: New deal created in Attio\n"
        "Amazon Q — Dataset\n"
        "Deal value ($k): US$300.00\n"
        "Thread in deals-new | Apr 13th\n"
        "yes! exploring requirements.\n"
        "<@U123>: who_is_available"
    )
    assert is_likely_deal_notification_thread(thread)
    assert not is_team_capacity_query(thread)
    assert is_team_capacity_query(thread + "\nPlease share **team capacity** snapshot.")


def test_thread_suggests_full_team_intent_english_hints() -> None:
    assert thread_suggests_full_team_intent("Need a full team for the Shopify pilot")
    assert thread_suggests_full_team_intent("Who is free — we need team for scale on this")
    assert thread_suggests_full_team_intent("project team for the rollout")
    assert not thread_suggests_full_team_intent("Need one SoE for tier 3")
    assert not thread_suggests_full_team_intent("")


def test_only_role_from_thread_wfm() -> None:
    assert only_role_from_thread("Team capacity — only WFM please") == "wfm"
    assert only_role_from_thread("only SOE for this chase") == "soe"


def test_only_role_from_thread_soe_before_so() -> None:
    assert only_role_from_thread("only soe and nobody else") == "soe"


def test_only_role_none_without_keyword() -> None:
    assert only_role_from_thread("need a DPM for tier 2") is None


def test_multi_roles_from_thread_ordered_with_conjunctive() -> None:
    assert multi_roles_from_thread("need SoE and DPM for tier 3") == ["soe", "dpm"]
    assert multi_roles_from_thread("Looking for WFM, QM — staffing help") == ["wfm", "qm"]


def test_multi_roles_from_thread_rejects_or_and_team_capacity() -> None:
    assert multi_roles_from_thread("need SoE or DPM for tier 3") == []
    assert multi_roles_from_thread("Team capacity — need SoE, DPM") == []


def test_rfp_shape_excludes_loose_team_capacity_heuristic() -> None:
    """Marketing/proposal language must not route to org-wide capacity when thread is RFP-shaped."""
    t = (
        "Responding to a customer RFP for evaluation pipelines. "
        "What's our team capacity — who might be available to join scoping calls?"
    )
    assert thread_suggests_pre_sales_rfp_deal_shape(t)
    assert not is_team_capacity_query(t)
