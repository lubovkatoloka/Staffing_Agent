"""Strip Notion/markdown junk from pasted SQL so `databricks ... query` gets valid SQL."""

from __future__ import annotations

import re


def sanitize_sql_for_cli(sql: str) -> str:
    """
    - Remove markdown fence lines (```sql / ```).
    - Trim everything before the first top-level WITH or SELECT (drops "- Occupation SQL", titles).
    - Whitespace-normalize to a single line (CLI expects one argument).
    """
    lines: list[str] = []
    for ln in sql.splitlines():
        s = ln.strip()
        if s.startswith("```"):
            continue
        lines.append(ln)
    text = "\n".join(lines)

    m = re.search(r"^\s*(with|select)\b", text, re.MULTILINE | re.IGNORECASE)
    if m:
        text = text[m.start() :]

    one = " ".join(text.split())
    return one.strip()
