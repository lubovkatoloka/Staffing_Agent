from staffing_agent.node3_project_staffing import format_project_staffing_markdown


def test_format_project_staffing_matches_name_in_role_columns() -> None:
    rows = [
        {
            "name": "Proj One",
            "client_name": "Acme",
            "stage": "building",
            "status": "ON_TRACK",
            "dpm": "Alice Smith - dpm",
            "soe": "Bob - soe",
        },
        {
            "name": "Proj Two",
            "client_name": "Beta",
            "stage": "discovery",
            "status": "ON_TRACK",
            "soe": "Alice Smith - soe",
        },
    ]
    text = format_project_staffing_markdown(rows, ["Alice Smith"])
    assert "Alice Smith" in text
    assert "Proj One" in text
    assert "Proj Two" in text
    assert "dpm" in text or "soe" in text


def test_format_empty_when_no_names() -> None:
    rows = [{"name": "X", "dpm": "Someone"}]
    assert format_project_staffing_markdown(rows, []) == ""


def test_format_no_match_shows_note() -> None:
    rows = [{"name": "P", "dpm": "Other Person"}]
    text = format_project_staffing_markdown(rows, ["Alice"])
    assert "нет проектов" in text
