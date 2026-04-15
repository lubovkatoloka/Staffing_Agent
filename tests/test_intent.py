import pytest

from staffing_agent.intent import (
    is_bare_slack_capacity_mention_trigger,
    is_likely_deal_notification_thread,
    is_team_capacity_query,
    slack_trigger_visible_text,
)


def test_team_capacity_phrases() -> None:
    assert is_team_capacity_query("Team capacity @who_is_available")
    assert is_team_capacity_query("кто свободен на неделе")
    assert is_team_capacity_query("who is available for a call")


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
