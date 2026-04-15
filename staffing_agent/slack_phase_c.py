"""Phase C footer: decision demo + optional Databricks smoke."""

from __future__ import annotations

import os

from staffing_agent.config_loader import load_decision_config
from staffing_agent.databricks_cli import databricks_profile, run_sql_query, smoke_sql_text
from staffing_agent.decision import classify_availability


def _slack_dbx_smoke_enabled() -> bool:
    return os.environ.get("STAFFING_AGENT_SLACK_DBX_SMOKE", "").strip() in ("1", "true", "yes")


def build_phase_c_section() -> str:
    """
    Short Slack block: example availability classification + optional DBX smoke.
    Full Occupation/PTO SQL from Notion is not wired yet.
    """
    cfg = load_decision_config()
    demo = classify_availability(
        0.62,
        active_project_count=2,
        decision_cfg=cfg,
    )
    lines = [
        "*Phase C — decision engine (demo)*",
        f"_Example:_ occupation=0.62, active_projects=2 → `{demo.label.value}` ({demo.notes or 'band'})",
        "_The main “who can take the project” recommendation is in the *Recommendation* block in Node 3 above; here is only a demo of the bands._",
    ]

    prof = databricks_profile()
    if prof and _slack_dbx_smoke_enabled():
        ok, msg = run_sql_query(smoke_sql_text())
        if ok:
            clip = msg[:1200] + ("…" if len(msg) > 1200 else "")
            lines.append(f"*Databricks smoke* (`{prof}`): ```{clip}```")
        else:
            lines.append(f"*Databricks smoke failed:* `{msg[:500]}`")
    elif prof:
        lines.append(
            "_Databricks:_ profile is set; set `STAFFING_AGENT_SLACK_DBX_SMOKE=1` to run `SELECT 1` in this reply "
            "(or use `python -m staffing_agent --check-dbx`)._"
        )
    else:
        lines.append(
            "_Databricks:_ set `DATABRICKS_PROFILE` in `.env` for CLI smoke (`--check-dbx`)._"
        )

    return "\n".join(lines)
