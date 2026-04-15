"""
Node 3 — Databricks: Occupation SQL (+ optional PTO SQL, Active projects SQL) from Decision Logic v1.0.

Paste queries from Notion into sql/*.sql. Large Occupation query often already merges PTO; extra files are for
separate snapshots from the same spec page.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, Optional

from staffing_agent.config_loader import load_decision_config
from staffing_agent.databricks_cli import databricks_profile, run_sql_query
from staffing_agent.node3_role_buckets import format_role_bucket_fallback, format_role_bucket_section
from staffing_agent.node4_recommendation import build_project_recommendation_markdown


def _maybe_project_staffing_markdown(
    occupation_rows: list[dict[str, Any]],
    *,
    tier: Optional[int],
    decision_cfg: dict[str, Any],
    project_type_tags: Optional[list[str]],
    summary: str,
    timeout_sec: int,
    preloaded_ps_rows: Optional[list[dict[str, Any]]] = None,
) -> str:
    from staffing_agent.node3_project_staffing import fetch_project_staffing_addon

    return fetch_project_staffing_addon(
        occupation_rows,
        tier=tier,
        decision_cfg=decision_cfg,
        project_type_tags=project_type_tags or [],
        summary=summary or "",
        timeout_sec=timeout_sec,
        preloaded_ps_rows=preloaded_ps_rows,
    )
from staffing_agent.projects_classification import append_similar_projects_to_lines
from staffing_agent.node3_tier_preview import occupation_preview_caption_suffix, occupation_preview_roles
from staffing_agent.reply_template import (
    COMPACT_OCCUPATION_PREVIEW_ROWS,
    FULL_OCCUPATION_PREVIEW_ROWS,
    COMPACT_PTO_NAME_SAMPLES,
    reply_style,
)
from staffing_agent.spec_nodes_slack import (
    followup_decision_nodes_compact,
    node3_checklist_intro,
    node3_checklist_intro_compact,
    node4_5_section_markdown,
    node4_section_markdown,
    node5_section_markdown,
)
from staffing_agent.node3_row_utils import name_value as _name_value
from staffing_agent.node3_row_utils import occupation_value as _occupation_value
from staffing_agent.node3_row_utils import project_role_norm

_ROOT = Path(__file__).resolve().parent.parent

MIN_OCCUPATION_SQL_LEN = 80


def _staffing_stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
MIN_OPTIONAL_SQL_LEN = 40


def occupation_sql_path() -> Path:
    override = (os.environ.get("STAFFING_OCCUPATION_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "sql" / "occupation.sql"


def pto_sql_path() -> Path:
    override = (os.environ.get("STAFFING_PTO_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "sql" / "pto.sql"


def active_projects_sql_path() -> Path:
    override = (os.environ.get("STAFFING_ACTIVE_PROJECTS_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "sql" / "active_projects.sql"


def _sql_executable_text(path: Path) -> str:
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    return "\n".join(lines).strip()


def _try_parse_query_json(raw: str) -> list[dict[str, Any]] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        for k in ("result", "data", "rows", "results"):
            v = data.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return None


def _run_query_json_first(sql_text: str, *, timeout_sec: int) -> tuple[bool, str]:
    ok, out = run_sql_query(
        sql_text,
        timeout_sec=timeout_sec,
        extra_args=["--output", "json"],
    )
    if not ok:
        ok, out = run_sql_query(sql_text, timeout_sec=timeout_sec)
    return ok, out


def _row_preview(row: dict[str, Any], *, max_keys: int = 5, max_len: int = 180) -> str:
    keys = list(row.keys())[:max_keys]
    parts = [f"{k}={row[k]}" for k in keys]
    s = ", ".join(parts)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _format_generic_rows(rows: list[dict[str, Any]], *, max_rows: int) -> list[str]:
    out: list[str] = []
    for r in rows[:max_rows]:
        out.append(f"• {_row_preview(r)}")
    if len(rows) > max_rows:
        out.append(f"… _and {len(rows) - max_rows} more rows_")
    return out


def _sample_name_from_row(r: dict[str, Any]) -> str:
    for k in ("user_name", "name", "USER_NAME"):
        v = r.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()[:120]
    for k, v in r.items():
        if "name" in k.lower() and v is not None and str(v).strip():
            return str(v).strip()[:120]
    return "?"


def _section_optional_query(
    *,
    title: str,
    path: Path,
    prof: str,
    timeout_sec: int,
    min_sql_len: int,
    max_rows: int,
    mode: Literal["compact", "full"] = "full",
) -> list[str]:
    sql_text = _sql_executable_text(path)
    try:
        rel = path.relative_to(_ROOT)
    except ValueError:
        rel = path

    if len(sql_text) < min_sql_len:
        return [
            f"_{title}: optional — paste SQL from Notion into `{rel}`._",
        ]

    ok, out = _run_query_json_first(sql_text, timeout_sec=timeout_sec)
    if not ok:
        return [f"*{title}* _(query failed)_", f"```{out[:1200]}{'…' if len(out) > 1200 else ''}```"]

    rows = _try_parse_query_json(out)
    if not rows:
        clip = out[:4000] + ("…" if len(out) > 4000 else "")
        return [
            f"*{title}* _(non-JSON or empty; raw output)_",
            f"```{clip}```",
        ]

    if mode == "compact":
        if "active" in title.lower():
            return [
                f"*{title}* _({len(rows)} rows in snapshot)_ — _project list omitted in compact reply._",
                f"_Full export — SQL file or Databricks. Profile `{prof}`._",
            ]
        names = [_sample_name_from_row(r) for r in rows[:COMPACT_PTO_NAME_SAMPLES]]
        tail = f" _+{len(rows) - len(names)}_…" if len(rows) > len(names) else ""
        ns = ", ".join(names)
        return [
            f"*{title}* _({len(rows)} people)_ — {ns}{tail}",
            f"_Details — `pto.sql` / Databricks. Profile `{prof}`._",
        ]

    lines = [f"*{title}* _({len(rows)} rows, show {min(max_rows, len(rows))})_", *_format_generic_rows(rows, max_rows=max_rows)]
    lines.append(f"_Profile `{prof}`._")
    return lines


def _followup_block(tier: Optional[int], *, compact: bool) -> list[str]:
    if compact:
        return [followup_decision_nodes_compact(tier)]
    return [
        node4_section_markdown(tier),
        "",
        node4_5_section_markdown(),
        "",
        node5_section_markdown(),
    ]


def node3_slack_markdown(
    *,
    timeout_sec: int = 300,
    tier: Optional[int] = None,
    project_type_tags: Optional[list[str]] = None,
    summary: str = "",
) -> str:
    """Run occupation + optional PTO + optional active projects SQL; return Slack mrkdwn."""
    cfg = load_decision_config()
    prof = databricks_profile()
    rs = reply_style()
    minimal = rs == "minimal"
    compact = rs == "compact"
    full = rs == "full"
    checklist = (
        node3_checklist_intro_compact()
        if (compact or minimal)
        else node3_checklist_intro()
    )

    spec_blurb = (
        "_Source: Databricks (`occupation.sql`, optional PTO / active projects) — "
        f"<https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4|Decision Logic v1.0>._"
        if (compact or minimal)
        else (
            "_Notion spec:_ [Decision Logic v1.0](https://www.notion.so/toloka-ai/Staffing-Agent-Decision-Logic-v1-0-32749d0688568183af3bf80ff6aedfd4) "
            "(Occupation SQL, PTO SQL, optional Active projects list). "
            "Merged `total_occupation` is defined in the spec; large Occupation query may already include PTO._"
        )
    )
    lines: list[str] = [
        "*Node 3 — availability (Databricks)*",
        checklist,
        spec_blurb,
    ]
    om: Literal["compact", "full"] = "compact" if (compact or minimal) else "full"

    if not prof:
        if minimal:
            return "_Occupation unavailable:_ set `DATABRICKS_PROFILE` in `.env` and install `databricks` CLI._"
        lines.append(
            "_Set `DATABRICKS_PROFILE` in `.env` and install `databricks` CLI. "
            "Add SQL files under `sql/` (see `sql/pto.sql`, `sql/active_projects.sql`)._"
        )
        lines.append("")
        lines.append(format_role_bucket_fallback("DATABRICKS_PROFILE is not set.", tier=tier))
        lines.append("")
        if full:
            lines.append("\n".join(_followup_block(tier, compact=False)))
            append_similar_projects_to_lines(
                lines, project_type_tags=project_type_tags, summary=summary
            )
        return "\n".join(lines)

    # --- Occupation (main) ---
    path_occ = occupation_sql_path()
    sql_occ = _sql_executable_text(path_occ)
    if len(sql_occ) < MIN_OCCUPATION_SQL_LEN:
        if minimal:
            try:
                rel = path_occ.relative_to(_ROOT)
            except ValueError:
                rel = path_occ
            return f"_No Occupation query in `{rel}` — paste SQL from Notion._"
        try:
            rel = path_occ.relative_to(_ROOT)
        except ValueError:
            rel = path_occ
        lines.append(
            f"_Paste the full *Occupation SQL* from Notion into `{rel}` "
            "(or `STAFFING_OCCUPATION_SQL_PATH`)._"
        )
        lines.append("")
        lines.extend(
            _section_optional_query(
                title="PTO snapshot (separate query)",
                path=pto_sql_path(),
                prof=prof,
                timeout_sec=min(timeout_sec, 180),
                min_sql_len=MIN_OPTIONAL_SQL_LEN,
                max_rows=20,
                mode=om,
            )
        )
        lines.append("")
        lines.extend(
            _section_optional_query(
                title="Active projects (separate query)",
                path=active_projects_sql_path(),
                prof=prof,
                timeout_sec=min(timeout_sec, 180),
                min_sql_len=MIN_OPTIONAL_SQL_LEN,
                max_rows=15,
                mode=om,
            )
        )
        lines.append("")
        lines.append(format_role_bucket_fallback("Add full SQL to sql/occupation.sql.", tier=tier))
        lines.append("")
        if full:
            lines.append("\n".join(_followup_block(tier, compact=False)))
            append_similar_projects_to_lines(
                lines, project_type_tags=project_type_tags, summary=summary
            )
        return "\n".join(lines)

    _staffing_stderr("[staffing] Databricks: running sql/occupation.sql …")
    t_occ = time.perf_counter()
    ok, out = _run_query_json_first(sql_occ, timeout_sec=timeout_sec)
    _staffing_stderr(
        f"[staffing] Databricks: occupation.sql finished in {time.perf_counter() - t_occ:.1f}s "
        f"(ok={ok}, ~{len(out)} chars raw output)"
    )
    if not ok:
        if minimal:
            clip = out[:400] + ("…" if len(out) > 400 else "")
            return f"_Occupation query failed:_ `{clip}`"
        lines.append(f"_Occupation query failed:_ `{out[:900]}{'…' if len(out) > 900 else ''}`")
        lines.append("")
        lines.append(format_role_bucket_fallback("Occupation query did not run (see error above).", tier=tier))
        lines.append("")
        if full:
            lines.append("\n".join(_followup_block(tier, compact=False)))
            append_similar_projects_to_lines(
                lines, project_type_tags=project_type_tags, summary=summary
            )
        return "\n".join(lines)

    rows = _try_parse_query_json(out)
    if not rows:
        if minimal:
            return "_Occupation response is not a JSON array — check output in Databricks._"
        clip = out[:6000] + ("…" if len(out) > 6000 else "")
        lines.append("_Occupation: raw output (JSON parse failed):_")
        lines.append(f"```{clip}```")
        lines.append("")
        lines.append(
            format_role_bucket_fallback(
                "Response is not a JSON array — could not bucket by role.",
                tier=tier,
            )
        )
    else:
        from staffing_agent.decision import classify_availability

        occ_cfg = cfg.get("occupation") or {}
        role_filter = occupation_preview_roles(tier)
        if role_filter is not None:
            preview_rows = [r for r in rows if project_role_norm(r) in role_filter]
        else:
            preview_rows = list(rows)

        def sort_key(r: dict[str, Any]) -> float:
            o = _occupation_value(r)
            return o if o is not None else 1.0

        preview_n = COMPACT_OCCUPATION_PREVIEW_ROWS if compact else FULL_OCCUPATION_PREVIEW_ROWS
        sorted_rows = sorted(preview_rows, key=sort_key)[:preview_n]

        project_staffing_snapshot: Optional[list[dict[str, Any]]] = None
        if tier in (1, 2, 3, 4):
            from staffing_agent.node3_project_staffing import fetch_project_staffing_rows

            project_staffing_snapshot = fetch_project_staffing_rows(
                timeout_sec=min(timeout_sec, 180),
            )

        rec = build_project_recommendation_markdown(
            rows,
            tier=tier,
            decision_cfg=cfg,
            project_type_tags=project_type_tags or [],
            summary=summary or "",
            detail="minimal" if minimal else "standard",
            project_staffing_rows=project_staffing_snapshot,
        )
        if minimal:
            ps = _maybe_project_staffing_markdown(
                rows,
                tier=tier,
                decision_cfg=cfg,
                project_type_tags=project_type_tags,
                summary=summary or "",
                timeout_sec=min(timeout_sec, 180),
                preloaded_ps_rows=project_staffing_snapshot,
            )
            return f"{rec}\n\n{ps}" if ps else rec

        def _occ_table_lines() -> list[str]:
            out: list[str] = []
            if compact:
                out.append(
                    f"*Load summary (Occupation)* _({len(rows)} rows in SQL; "
                    f"{occupation_preview_caption_suffix(tier, max_shown=preview_n)})_"
                )
            else:
                out.append(
                    f"*Occupation table* _({len(rows)} rows in query; "
                    f"{occupation_preview_caption_suffix(tier, max_shown=preview_n)})_"
                )
            if role_filter is not None and not preview_rows:
                out.append(
                    "_No one matched the role filter for this Tier — check `project_role` in the output or see full result in Databricks._"
                )
            for r in sorted_rows:
                occ = _occupation_value(r)
                name = _name_value(r)
                if occ is None:
                    label = "?"
                else:
                    t = max(0.0, min(1.0, float(occ)))
                    apc = 0 if t == 0.0 else 1
                    av = classify_availability(t, active_project_count=apc, decision_cfg=cfg)
                    label = av.label.value
                disp_occ = f"{float(occ) * 100:.0f}%" if occ is not None else "n/a"
                out.append(f"• {name} — {disp_occ} → `{label}`")
            fb = float(occ_cfg.get("free_below", 0.5))
            pb = float(occ_cfg.get("partial_below", 0.8))
            out.append(
                f"_Bands: FREE below {fb:.0%}, PARTIAL below {pb:.0%} (`config/decision_logic.yaml`)._"
            )
            return out

        if compact:
            lines.append(rec)
            lines.append("")
            lines.extend(_occ_table_lines())
            lines.append("_Full list — Databricks / `occupation.sql`._")
            ps_c = _maybe_project_staffing_markdown(
                rows,
                tier=tier,
                decision_cfg=cfg,
                project_type_tags=project_type_tags,
                summary=summary or "",
                timeout_sec=min(timeout_sec, 180),
                preloaded_ps_rows=project_staffing_snapshot,
            )
            if ps_c:
                lines.append("")
                lines.append(ps_c)
        else:
            lines.extend(_occ_table_lines())
            lines.append("")
            lines.append(format_role_bucket_section(rows, decision_cfg=cfg, tier=tier))
            lines.append("")
            lines.append(rec)

    if full:
        append_similar_projects_to_lines(
            lines, project_type_tags=project_type_tags, summary=summary
        )

        lines.append("")
        lines.extend(
            _section_optional_query(
                title="PTO snapshot (separate query from Notion)",
                path=pto_sql_path(),
                prof=prof,
                timeout_sec=min(timeout_sec, 180),
                min_sql_len=MIN_OPTIONAL_SQL_LEN,
                max_rows=20,
                mode=om,
            )
        )
        lines.append("")
        lines.extend(
            _section_optional_query(
                title="Active projects (separate query from Notion)",
                path=active_projects_sql_path(),
                prof=prof,
                timeout_sec=min(timeout_sec, 180),
                min_sql_len=MIN_OPTIONAL_SQL_LEN,
                max_rows=15,
                mode=om,
            )
        )

        lines.append("")
        lines.append("\n".join(_followup_block(tier, compact=False)))

    return "\n".join(lines)
