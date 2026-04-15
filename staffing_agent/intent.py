"""Rough intent detection from thread text (no LLM)."""

from __future__ import annotations

import re

# Slack user/channel/group tokens — not user-authored wording.
_SLACK_TRIGGER_MARKUP_RE = re.compile(
    r"<@[^>]+>|<![^>]+>|<#[^>]+>",
)

# NBSP and other unicode spaces — Slack / CRM pastes often break substring checks ("deal\u00a0value").
_WS_CLASS = re.compile(r"[\xa0\u2009\u200b\u200c\u200d\ufeff]+")


def _normalize_slack_thread_text(s: str) -> str:
    """Lowercase, normalize spaces, map underscores to spaces (for who_is_available handle matching)."""
    t = _WS_CLASS.sub(" ", (s or "").lower())
    t = re.sub(r" +", " ", t).strip()
    return t.replace("_", " ")


def slack_trigger_visible_text(text: str) -> str:
    """
    Text left after removing user mentions, !here / !subteam, and channel links.
    Used to detect a bare @bot ping (same intent as “who is available” without typing it).
    """
    t = (text or "").strip()
    t = _SLACK_TRIGGER_MARKUP_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def is_bare_slack_capacity_mention_trigger(text: str) -> bool:
    """
    True when the app_mention event text is only @bot (optional whitespace).
    Slack often omits the literal phrase “who is available” in the message body, so
    thread previews never match ``is_team_capacity_query`` unless we check the trigger.
    """
    return len(slack_trigger_visible_text(text)) == 0


def is_team_capacity_query(thread_plain: str, *, trigger_message_text: str | None = None) -> bool:
    """
    Queries like “Team capacity”, “who is available”, capacity overview — no specific project.

    Slack bot display names often appear as ``who_is_available`` (underscores). Normalizing
    underscores to spaces makes that match the same intent as the natural phrase.

    Pass ``trigger_message_text`` from the Slack ``app_mention`` event when available: a message that
    contains only ``<@U…>`` (no words) is treated like a “who’s free” ask for hint / classification
    purposes when the thread is not a deal-feed / CRM context.
    """
    if trigger_message_text is not None and is_bare_slack_capacity_mention_trigger(trigger_message_text):
        if is_likely_deal_notification_thread(thread_plain):
            return False
        return True

    t = _normalize_slack_thread_text(thread_plain)

    # Deal / CRM threads: the bot display name ``who_is_available`` becomes "who is available" after
    # underscore normalization — that must NOT route to generic team capacity. Same for the loose
    # ``capacity`` + ``available`` heuristic (marketing copy mentions "available datasets").
    if is_likely_deal_notification_thread(thread_plain):
        if "team capacity" in t or "teamcapacity" in t:
            return True
        if "загрузка команды" in t or "кто свободен" in t:
            return True
        return False

    if "team capacity" in t or "teamcapacity" in t:
        return True
    if "загрузка команды" in t or "кто свободен" in t:
        return True
    if "who is available" in t or "who's available" in t:
        return True
    if re.search(r"\bcapacity\b", t) and (
        "who" in t or "team" in t or "free" in t or "available" in t or "@" in t
    ):
        return True
    return False


def is_likely_deal_notification_thread(thread_plain: str) -> bool:
    """
    Heuristic: Attio / CRM «new deal» style paste (for logging, routing experiments, tests).
    Does not replace Phase B — use when you want to tag deal-feed threads in code.
    """
    t = _normalize_slack_thread_text(thread_plain)
    if "attio" in t and ("new deal" in t or "deal created" in t):
        return True
    if "deal value" in t or "deal value ($k)" in t:
        return True
    if "deals-new" in t or "thread in deals-new" in t:
        return True
    return False
