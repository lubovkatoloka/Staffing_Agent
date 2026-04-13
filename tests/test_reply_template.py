import os

from staffing_agent.reply_template import reply_style


def test_reply_style_defaults_to_minimal(monkeypatch):
    monkeypatch.delenv("STAFFING_AGENT_REPLY_STYLE", raising=False)
    assert reply_style() == "minimal"


def test_reply_style_compact(monkeypatch):
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "compact")
    assert reply_style() == "compact"


def test_reply_style_full(monkeypatch):
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "full")
    assert reply_style() == "full"
