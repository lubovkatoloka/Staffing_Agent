from staffing_agent.decision.node2_rules import node2_slack_markdown


def test_node2_tier2_contains_soe():
    text = node2_slack_markdown(2, ["Evals"])
    assert "SoE" in text
    assert "Tier 2" in text
    assert "Domain match" in text


def test_node2_tier_none():
    text = node2_slack_markdown(None, [])
    assert "tier" in text.lower()
