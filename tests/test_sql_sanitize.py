from staffing_agent.sql_sanitize import sanitize_sql_for_cli


def test_strips_markdown_fence_and_bullet():
    raw = """- Occupation SQL

    ```sql
    with x as (select 1 as a)
    select * from x
    ```
    """
    out = sanitize_sql_for_cli(raw)
    assert out.lower().startswith("with x as")
    assert "select * from x" in out.lower()


def test_already_clean_select():
    raw = "SELECT 1 AS ok"
    assert "select 1" in sanitize_sql_for_cli(raw).lower()
