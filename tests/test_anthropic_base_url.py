import staffing_agent.anthropic_llm as al


def test_anthropic_base_url_prefers_explicit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://a.example")
    monkeypatch.setenv("LITELLM_BASE_URL", "https://b.example")
    assert al.anthropic_base_url() == "https://a.example"


def test_anthropic_base_url_litellm_alias(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.internal")
    assert al.anthropic_base_url() == "https://proxy.internal"


def test_anthropic_base_url_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    assert al.anthropic_base_url() is None
