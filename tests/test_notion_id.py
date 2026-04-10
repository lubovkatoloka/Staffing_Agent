from staffing_agent.notion_fetch import notion_page_id_from_url


def test_notion_id_from_typical_workspace_url() -> None:
    u = "https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4"
    assert notion_page_id_from_url(u) == "32749d0688568183af3bf80ff6aedfd4"


def test_notion_id_non_notion() -> None:
    assert notion_page_id_from_url("https://example.com/abc") is None
