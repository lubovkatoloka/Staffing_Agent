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


# Broader RFP / pre-sales / exploration shape (not necessarily exact "RFP" token).
_PRE_SALES_RFP_SHAPE = re.compile(
    r"(?i)\b("
    r"rfp\b|request\s+for\s+proposal|pre[-\s]?sales|presales|scoping\b|\bproposal\b|"
    r"statement\s+of\s+work|\bsow\b|\bbid\b|tender\b|pitch\b|"
    r"respond(?:ing)?\s+to\s+(?:an?\s+)?rfp|rfp\s+response|"
    r"shape\s+(?:the\s+)?(?:deal|scope)|deal\s+shape|feasibility"
    r")\b"
)


def thread_suggests_pre_sales_rfp_deal_shape(thread_plain: str) -> bool:
    """
    True when the thread reads like RFP / pre-sales / deal shaping, not a generic org-wide capacity snapshot.

    Used to avoid routing rich deal+RFP pastes to *TEAM CAPACITY — OVERVIEW* just because they contain
    words like ``capacity``, ``team``, and ``available`` in proposal or staffing language.
    """
    if not (thread_plain or "").strip():
        return False
    t = _normalize_slack_thread_text(thread_plain)
    if _PRE_SALES_RFP_SHAPE.search(t):
        return True
    if is_likely_deal_notification_thread(thread_plain) and re.search(
        r"(?i)\b("
        r"explor(?:ing|atory)|early[-\s]?stage|requirements?\b|discovery\b|qualification\b|"
        r"client\s+ask|sizing\b|ballpark\b"
        r")\b",
        t,
    ):
        return True
    return False


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
        if thread_suggests_pre_sales_rfp_deal_shape(thread_plain):
            return False
        return True
    if "загрузка команды" in t or "кто свободен" in t:
        return True
    if "who is available" in t or "who's available" in t:
        if thread_suggests_pre_sales_rfp_deal_shape(thread_plain):
            return False
        return True
    if re.search(r"\bcapacity\b", t) and (
        "who" in t or "team" in t or "free" in t or "available" in t or "@" in t
    ):
        if thread_suggests_pre_sales_rfp_deal_shape(thread_plain):
            return False
        return True
    return False


def thread_has_availability_capacity_ping(thread_plain: str) -> bool:
    """
    True when the thread includes wording like “who is available”, ``who_is_available`` (underscores
    normalized), or “team capacity” — i.e. Delivery is being asked for a capacity snapshot, not only FYI.

    Used with :func:`is_likely_deal_notification_thread` so Phase B can assign a hypothesis tier when a
    CRM/deal paste is paired with an availability ping.
    """
    t = _normalize_slack_thread_text(thread_plain)
    if "who is available" in t or "who's available" in t:
        return True
    if "team capacity" in t or "teamcapacity" in t:
        return True
    if "загрузка команды" in t or "кто свободен" in t:
        return True
    return False


_ONLY_ROLE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("soe", re.compile(r"(?i)\bonly\s+(?:an?\s+)?(?:ssoe|soe|solution\s+engineers?)\b")),
    ("dpm", re.compile(r"(?i)\bonly\s+(?:an?\s+)?dpm?s?\b")),
    ("wfm", re.compile(r"(?i)\bonly\s+(?:an?\s+)?(?:wfm|wfc)\b")),
    ("qm", re.compile(r"(?i)\bonly\s+(?:an?\s+)?qm\b")),
    ("se", re.compile(r"(?i)\bonly\s+(?:an?\s+)?(?:se\b|software\s+engineers?)\b")),
    ("so", re.compile(r"(?i)\bonly\s+(?:an?\s+)?(?:accountable\s+)?so\b(?!\w)")),
)


def only_role_from_thread(thread_plain: str) -> str | None:
    """
    English **only <role>** constraint — capacity / staffing must not bleed into other slices (CR-8).
    Checked before generic team capacity routing.
    """
    if not (thread_plain or "").strip():
        return None
    t = thread_plain
    for key, pat in _ONLY_ROLE_PATTERNS:
        if pat.search(t):
            return key
    return None


_MULTI_ROLE_TOKEN_RE = re.compile(
    r"(?i)(?P<tok>"
    r"ssoe|soe|solution\s+engineers?|"
    r"dpm?s?|"
    r"wfm|wfc|"
    r"\bqm\b|"
    r"software\s+engineers?|\bse\b|"
    r"(?:need|want)\s+1\s+so\b|accountable\s+so\b|\bso\b"
    r")"
)


def _role_key_from_token_match(raw: str) -> str | None:
    t = (raw or "").lower().strip()
    if not t:
        return None
    if "solution" in t or t in ("ssoe", "soe"):
        return "soe"
    if "dpm" in t:
        return "dpm"
    if "wfm" in t or "wfc" in t:
        return "wfm"
    if t == "qm":
        return "qm"
    if "software" in t or t == "se":
        return "se"
    if t == "so" or "accountable" in t or re.search(r"need|want", t):
        return "so"
    return None


def multi_roles_from_thread(thread_plain: str) -> list[str]:
    """
    Two or more distinct role buckets in one staffing ask (S3), in thread order.

    Requires a conjunctive separator (comma / and / & / +) so ``SoE or DPM`` does not trigger.
    """
    if not (thread_plain or "").strip():
        return []
    if is_team_capacity_query(thread_plain):
        return []
    if not re.search(r"(?i)(\b(?:and|&|\+)\b|,\s*)", thread_plain):
        return []
    has_tier = bool(re.search(r"(?i)\btier\s*[1-4]\b", thread_plain))
    staffingish = bool(
        re.search(
            r"(?i)\b(need|want|looking\s+for|hire|staff(?:ing)?|find|open\s+role|req(?:uire)?|"
            r"candidate|кого|нужен|нужна|нужны)\b",
            thread_plain,
        )
    ) or has_tier
    if not staffingish:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for m in _MULTI_ROLE_TOKEN_RE.finditer(thread_plain):
        key = _role_key_from_token_match(m.group("tok"))
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(key)
    if len(found) < 2:
        return []
    return found


def single_role_focus_from_thread(thread_plain: str) -> str | None:
    """
    Detect a narrow staffing ask for one role (SoE, DPM, WFM, QM, SO) without using team-wide capacity wording.

    Returns normalized bucket key: ``soe``, ``dpm``, ``wfm``, ``qm``, or ``so`` (accountable SO pool).
    """
    if not (thread_plain or "").strip():
        return None
    if is_team_capacity_query(thread_plain):
        return None
    tl = (thread_plain or "").lower()
    has_tier = bool(re.search(r"(?i)\btier\s*[1-4]\b", thread_plain))
    staffingish = bool(
        re.search(
            r"(?i)\b(need|want|looking\s+for|hire|staff(?:ing)?|find|open\s+role|req(?:uire)?|"
            r"candidate|кого|нужен|нужна|нужны)\b",
            thread_plain,
        )
    ) or has_tier
    if not staffingish:
        return None
    if re.search(r"(?i)\b(need|want)\s+1\s+so\b(?!\w)|\baccountable\s+so\b", tl):
        return "so"
    if re.search(r"(?i)\b(ssoe|soe|solution\s+engineer)\b", tl):
        return "soe"
    if re.search(r"(?i)\bdpm\b", tl):
        return "dpm"
    if re.search(r"(?i)\bwfm\b|\bwfc\b", tl):
        return "wfm"
    if re.search(r"(?i)\bqm\b", tl):
        return "qm"
    return None


def thread_suggests_full_team_intent(
    thread_plain: str, *, trigger_message_text: str | None = None
) -> bool:
    """
    English hints that the requester wants a full production / scale team view, not only a narrow slice.

    Uses the full thread text; the Slack trigger line alone is usually too thin.
    """
    _ = trigger_message_text
    if not (thread_plain or "").strip():
        return False
    t = _normalize_slack_thread_text(thread_plain)
    if "full team" in t or "team for scale" in t or "project team" in t:
        return True
    if "whole team" in t or "entire team" in t:
        return True
    if re.search(r"\bteam\b", t) and re.search(
        r"\b(for\s+scale|at\s+scale|production|full\s+delivery|all\s+roles|every\s+role)\b", t
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
