"""Live Notion exclusions (Ticket #4)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from staffing_agent.exclusions import (
    CACHE_TTL_SECONDS,
    ExcludedPerson,
    ExclusionResult,
    ExclusionStore,
    ExclusionUnavailableError,
    format_excluded_comment_block,
    match_hard_exclude,
    normalize_call_support_role_tags,
    record_matches_any_call_support_tag,
    reset_exclusion_store,
    role_tag_matches_call_support_filter,
)


def test_match_hard_exclude_substring():
    assert ExclusionStore._match_hard_exclude("Do Not Staff until Q3") == "do not staff"
    assert ExclusionStore._match_hard_exclude("currently unavailable") == "unavailable"
    assert ExclusionStore._match_hard_exclude("onboarding new SoE") == "onboarding"


def test_match_hard_exclude_dns_word_boundary():
    assert match_hard_exclude("DNS") == "DNS"
    assert match_hard_exclude("Note: DNS, see HR.") == "DNS"
    assert match_hard_exclude("DNStest") is None
    assert match_hard_exclude("medns") is None


def test_match_hard_exclude_negative():
    assert match_hard_exclude("only agentic projects") is None
    assert match_hard_exclude("PTO until 2026-05-15") is None
    assert match_hard_exclude("") is None
    assert match_hard_exclude("speaks Russian and Hebrew") is None


@pytest.mark.no_fake_exclusions
def test_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_exclusion_store()
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    calls: list[int] = []

    def fetch(self: ExclusionStore, token: str) -> ExclusionResult:
        calls.append(1)
        return ExclusionResult(excluded=tuple(), fetched_at=mock_now[0])

    mock_now = [0.0]
    monkeypatch.setattr(time, "time", lambda: mock_now[0])
    monkeypatch.setattr(ExclusionStore, "_fetch_live", fetch)
    store = ExclusionStore()
    store.get()
    mock_now[0] = 50.0
    store.get()
    assert len(calls) == 1
    mock_now[0] = float(CACHE_TTL_SECONDS + 50)
    store.get()
    assert len(calls) == 2


@pytest.mark.no_fake_exclusions
def test_fallback_to_stale_cache_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_exclusion_store()
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    stale = ExclusionResult(excluded=tuple(), fetched_at=time.time() - 99999.0)
    store = ExclusionStore()
    store._cached = stale

    def boom(self: ExclusionStore, token: str) -> ExclusionResult:
        raise RuntimeError("network down")

    monkeypatch.setattr(ExclusionStore, "_fetch_live", boom)
    assert store.get() is stale


@pytest.mark.no_fake_exclusions
def test_no_cache_no_live_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    reset_exclusion_store()
    store = ExclusionStore()
    with pytest.raises(ExclusionUnavailableError):
        store.get()


@pytest.mark.no_fake_exclusions
def test_fetch_live_respects_staffing_pool_and_matcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    reset_exclusion_store()

    page_ok = {
        "object": "page",
        "properties": {
            "Email": {"type": "email", "email": "ada@toloka.ai"},
            "Name": {"type": "title", "title": [{"plain_text": "Ada"}]},
            "Role Tag": {"type": "select", "select": {"name": "SSOE+SOE"}},
            "Comment": {"type": "rich_text", "rich_text": [{"plain_text": "onboarding"}]},
        },
    }
    page_only_agentic = {
        "object": "page",
        "properties": {
            "Email": {"type": "email", "email": "mario@toloka.ai"},
            "Name": {"type": "title", "title": [{"plain_text": "Mario"}]},
            "Role Tag": {"type": "select", "select": {"name": "DPM"}},
            "Comment": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "only agentic projects"}],
            },
        },
    }
    page_wrong_pool = {
        "object": "page",
        "properties": {
            "Email": {"type": "email", "email": "x@toloka.ai"},
            "Name": {"type": "title", "title": [{"plain_text": "X"}]},
            "Role Tag": {"type": "select", "select": {"name": "Acquisition Manager"}},
            "Comment": {"type": "rich_text", "rich_text": [{"plain_text": "do not staff"}]},
        },
    }

    def qp(self: ExclusionStore, token: str):
        return [page_ok, page_only_agentic, page_wrong_pool]

    monkeypatch.setattr(ExclusionStore, "_query_paginated", qp)
    store = ExclusionStore()
    res = store._fetch_live("tok")
    emails = {p.email for p in res.excluded}
    assert "ada@toloka.ai" in emails
    assert "mario@toloka.ai" not in emails
    assert "x@toloka.ai" in emails


def _patch_today(monkeypatch: pytest.MonkeyPatch, fixed: date) -> None:
    monkeypatch.setattr(
        "staffing_agent.exclusions.date",
        type("_D", (), {"today": staticmethod(lambda: fixed)}),
    )


def test_format_onboarding_footer_shows_header_and_day_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_today(monkeypatch, date(2026, 6, 15))
    res = ExclusionResult(
        excluded=(
            ExcludedPerson(
                email="ada@toloka.ai",
                name="Ada",
                role_tag="SSOE+SOE",
                comment="onboarding",
            ),
        ),
        fetched_at=0.0,
    )
    text = format_excluded_comment_block(
        res,
        frozenset({"soe"}),
        start_dates={"ada@toloka.ai": date(2026, 6, 1)},
    )
    assert "_Onboarding (excluded from picks):_" in text
    assert "Ada" in text
    assert "onboarding (14 days)" in text


def test_format_onboarding_sorts_by_days_since_hire_ascending(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_today(monkeypatch, date(2026, 6, 15))
    res = ExclusionResult(
        excluded=(
            ExcludedPerson(
                email="bob@t.com",
                name="Bob",
                role_tag="DPM",
                comment="onboarding",
            ),
            ExcludedPerson(
                email="ada@t.com",
                name="Ada",
                role_tag="SSOE+SOE",
                comment="onboarding new hire",
            ),
        ),
        fetched_at=0.0,
    )
    text = format_excluded_comment_block(
        res,
        frozenset({"soe", "dpm"}),
        start_dates={
            "bob@t.com": date(2026, 5, 1),
            "ada@t.com": date(2026, 6, 1),
        },
    )
    assert text.index("Ada") < text.index("Bob")


def test_format_onboarding_missing_start_date_last_and_unknown_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_today(monkeypatch, date(2026, 6, 15))
    res = ExclusionResult(
        excluded=(
            ExcludedPerson(
                email="zed@t.com",
                name="Zed",
                role_tag="DPM",
                comment="onboarding",
            ),
            ExcludedPerson(
                email="ada@t.com",
                name="Ada",
                role_tag="DPM",
                comment="onboarding",
            ),
        ),
        fetched_at=0.0,
    )
    text = format_excluded_comment_block(
        res,
        frozenset({"dpm"}),
        start_dates={"ada@t.com": date(2026, 6, 1)},
    )
    assert "(start date unknown)" in text
    assert text.index("Ada") < text.index("Zed")


def test_format_onboarding_empty_when_no_onboarding_comment_match() -> None:
    res = ExclusionResult(
        excluded=(
            ExcludedPerson(
                email="b@t.com",
                name="Bob",
                role_tag="DPM",
                comment="do not staff",
            ),
        ),
        fetched_at=0.0,
    )
    assert format_excluded_comment_block(res, frozenset({"dpm"})) == ""


def test_format_onboarding_only_includes_role_overlap() -> None:
    res = ExclusionResult(
        excluded=(
            ExcludedPerson(
                email="a@t.com",
                name="Ann",
                role_tag="SSOE+SOE",
                comment="onboarding",
            ),
            ExcludedPerson(
                email="b@t.com",
                name="Bob",
                role_tag="DPM",
                comment="onboarding",
            ),
        ),
        fetched_at=0.0,
    )
    text = format_excluded_comment_block(res, frozenset({"soe"}))
    assert "Ann" in text
    assert "Bob" not in text


def test_normalize_call_support_role_tags() -> None:
    assert normalize_call_support_role_tags(["dpm", "SSOE_SOE", "dpm"]) == ["DPM", "SSOE+SOE"]
    assert normalize_call_support_role_tags(["soe", "junk"]) == ["SOE"]


def test_role_tag_matches_call_support_filter() -> None:
    assert role_tag_matches_call_support_filter("SSOE+SOE", "SSOE+SOE")
    assert role_tag_matches_call_support_filter("DPM", "DPM")
    assert role_tag_matches_call_support_filter("SSOE+SOE", "SOE")
    assert not role_tag_matches_call_support_filter("DPM", "SSOE+SOE")


def test_record_matches_any_call_support_tag() -> None:
    assert record_matches_any_call_support_tag("SSOE+SOE / DPM", ["DPM"])
    assert record_matches_any_call_support_tag("SSOE+SOE", ["SSOE+SOE", "DPM"])
