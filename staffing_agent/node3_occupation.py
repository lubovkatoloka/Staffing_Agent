"""
Node 3 — Databricks: Capacity SQL (Capacity v2) merges workload + PTO flags per person/project row.

Paste queries from Notion into sql/capacity.sql.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, Optional

from staffing_agent.capacity_runtime import (
    default_new_project_weight,
    prepare_rows_for_recommendation,
)
from staffing_agent.config_loader import load_decision_config
from staffing_agent.databricks_cli import databricks_profile, run_sql_query
from staffing_agent.exclusions import (
    ExclusionUnavailableError,
    get_exclusion_store,
    slack_exclusion_unavailable_message,
)
from staffing_agent.node3_role_buckets import format_role_bucket_fallback, format_role_bucket_section
from staffing_agent.node4_recommendation import build_project_recommendation_markdown
from staffing_agent.projects_classification import append_similar_projects_to_lines
from staffing_agent.node3_tier_preview import occupation_preview_caption_suffix, occupation_preview_roles
from staffing_agent.reply_template import (
    COMPACT_OCCUPATION_PREVIEW_ROWS,
    FULL_OCCUPATION_PREVIEW_ROWS,
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
from staffing_agent.node3_row_utils import project_role_norm
from staffing_agent.staffing_csv import load_staffing_records

_ROOT = Path(__file__).resolve().parent.parent

MIN_CAPACITY_SQL_LEN = 80
MIN_OPTIONAL_SQL_LEN = 40


def _minimal_slack_error_clip(raw: str, *, max_len: int = 220) -> str:
    """Single-line, capped snippet for minimal Slack replies (avoid huge CLI OAuth dumps)."""
    s = " ".join((raw or "").split())
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _staffing_stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def capacity_sql_path() -> Path:
    override = (os.environ.get("STAFFING_CAPACITY_SQL_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    legacy = (os.environ.get("STAFFING_OCCUPATION_SQL_PATH") or "").strip()
    if legacy:
        return Path(legacy).expanduser()
    return _ROOT / "sql" / "capacity.sql"


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
    sese_path: bool = False,
) -> str:
    """Run sql/capacity.sql; return Slack mrkdwn."""
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
        "_Source: Databricks (`capacity.sql`) — "
        f"<https://www.notion.so/34b49d06885681468dd6d79d2e16d332|Staffing Agent v2 (Capacity)>._"
        if (compact or minimal)
        else (
            "_Notion spec:_ [Staffing Agent v2 — Capacity](https://www.notion.so/34b49d06885681468dd6d79d2e16d332). "
            "One row per person × active project; grouped in-app for bands and eligibility._"
        )
    )
    lines: list[str] = [
        "*Node 3 — availability (Databricks / Capacity v2)*",
        checklist,
        spec_blurb,
    ]

    if not prof:
        if minimal:
            return "_Capacity unavailable:_ set `DATABRICKS_PROFILE` in `.env` and install `databricks` CLI._"
        lines.append(
            "_Set `DATABRICKS_PROFILE` in `.env` and install `databricks` CLI. "
            "Add `sql/capacity.sql` from Notion._"
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

    path_cap = capacity_sql_path()
    sql_cap = _sql_executable_text(path_cap)
    if len(sql_cap) < MIN_CAPACITY_SQL_LEN:
        if minimal:
            try:
                rel = path_cap.relative_to(_ROOT)
            except ValueError:
                rel = path_cap
            return f"_No Capacity query in `{rel}` — paste SQL from Notion._"
        try:
            rel = path_cap.relative_to(_ROOT)
        except ValueError:
            rel = path_cap
        lines.append(
            f"_Paste the full *Capacity SQL* from Notion into `{rel}` "
            "(or `STAFFING_CAPACITY_SQL_PATH`)._"
        )
        lines.append("")
        lines.append(format_role_bucket_fallback("Add full SQL to sql/capacity.sql.", tier=tier))
        lines.append("")
        if full:
            lines.append("\n".join(_followup_block(tier, compact=False)))
            append_similar_projects_to_lines(
                lines, project_type_tags=project_type_tags, summary=summary
            )
        return "\n".join(lines)

    _staffing_stderr("[staffing] Databricks: running sql/capacity.sql …")
    t_cap = time.perf_counter()
    ok, out = _run_query_json_first(sql_cap, timeout_sec=timeout_sec)
    _staffing_stderr(
        f"[staffing] Databricks: capacity.sql finished in {time.perf_counter() - t_cap:.1f}s "
        f"(ok={ok}, ~{len(out)} chars raw output)"
    )
    if not ok:
        if minimal:
            clip = _minimal_slack_error_clip(out)
            return f"_Capacity query failed:_ `{clip}`"
        lines.append(f"_Capacity query failed:_ `{out[:900]}{'…' if len(out) > 900 else ''}`")
        lines.append("")
        lines.append(format_role_bucket_fallback("Capacity query did not run (see error above).", tier=tier))
        lines.append("")
        if full:
            lines.append("\n".join(_followup_block(tier, compact=False)))
            append_similar_projects_to_lines(
                lines, project_type_tags=project_type_tags, summary=summary
            )
        return "\n".join(lines)

    rows_raw = _try_parse_query_json(out)
    if not rows_raw:
        if minimal:
            return "_Capacity response is not a JSON array — check output in Databricks._"
        clip = out[:6000] + ("…" if len(out) > 6000 else "")
        lines.append("_Capacity: raw output (JSON parse failed):_")
        lines.append(f"```{clip}```")
        lines.append("")
        lines.append(
            format_role_bucket_fallback(
                "Response is not a JSON array — could not bucket by role.",
                tier=tier,
            )
        )
    else:
        try:
            exr = get_exclusion_store().get()
        except ExclusionUnavailableError:
            return slack_exclusion_unavailable_message(title="Staffing")

        staffing = load_staffing_records()
        npw = default_new_project_weight(cfg, tier)
        rows = prepare_rows_for_recommendation(
            rows_raw,
            decision_cfg=cfg,
            new_project_weight=npw,
            staffing=staffing,
            excluded_emails=exr.excluded_emails,
        )

        role_filter = occupation_preview_roles(tier)
        if role_filter is not None:
            preview_rows = [r for r in rows if project_role_norm(r) in role_filter]
        else:
            preview_rows = list(rows)

        def sort_key(r: dict[str, Any]) -> float:
            v = r.get("_capacity_verdict")
            return float(getattr(v, "capacity_used", 99.0))

        preview_n = COMPACT_OCCUPATION_PREVIEW_ROWS if compact else FULL_OCCUPATION_PREVIEW_ROWS
        sorted_rows = sorted(preview_rows, key=sort_key)[:preview_n]

        project_staffing_snapshot: Optional[list[dict[str, Any]]] = None
        if tier in (1, 2, 3, 4):
            from staffing_agent.node3_project_staffing import fetch_project_staffing_rows

            project_staffing_snapshot = fetch_project_staffing_rows(
                timeout_sec=min(timeout_sec, 180),
            )

        rec = build_project_recommendation_markdown(
            rows_raw,
            tier=tier,
            decision_cfg=cfg,
            project_type_tags=project_type_tags or [],
            summary=summary or "",
            detail="minimal" if minimal else "standard",
            project_staffing_rows=project_staffing_snapshot,
            sese_path=sese_path,
            exclusion_result=exr,
        )
        if minimal:
            return rec

        def _capacity_table_lines() -> list[str]:
            out: list[str] = []
            suffix = occupation_preview_caption_suffix(tier, max_shown=preview_n)
            if compact:
                out.append(f"*Load summary (Capacity)* _({len(rows)} people after grouping; {suffix})_")
            else:
                out.append(f"*Capacity table* _({len(rows)} people; {suffix})_")
            if role_filter is not None and not preview_rows:
                out.append(
                    "_No one matched the role filter for this Tier — check `role_group` / `project_role` or see Databricks._"
                )
            npw = default_new_project_weight(cfg, tier)
            for r in sorted_rows:
                verdict = r.get("_capacity_verdict")
                nm = _name_value(r)
                pr = project_role_norm(r) or "?"
                if verdict is None:
                    out.append(f"• {nm} — _missing verdict_")
                    continue
                cu = float(verdict.capacity_used)
                after = cu + npw
                band = verdict.band.value
                nproj = len(r.get("_capacity_rows") or ())
                soft = ""
                if verdict.is_soft and verdict.soft_reasons:
                    soft = " `[SOFT: " + ", ".join(s.value for s in verdict.soft_reasons) + "]`"
                pto = ""
                up = verdict.pto_upcoming_dates
                if up:
                    pto = f" `[⚠️ PTO {up[0]}..{up[1]}]`"
                el = "eligible" if verdict.eligible_for_new else f"ineligible `{verdict.ineligible_reason.value}`"
                out.append(
                    f"• {nm} · `{pr}` · `{band}` · *{cu:.2f}* → *{after:.2f}* after new · "
                    f"{nproj} projects {soft}{pto} · _{el}_"
                )
            fb = float((cfg.get("availability_bands") or {}).get("free_below", 1.0))
            pb = float((cfg.get("availability_bands") or {}).get("partial_below", 2.0))
            cap_u = float(cfg.get("cap_units", 2.0))
            out.append(
                f"_Bands: FREE below {fb:.2f}, PARTIAL below {pb:.2f}, cap units *{cap_u:.2f}* (`config/decision_logic.yaml`)._"
            )
            return out

        if compact:
            lines.append(rec)
            lines.append("")
            lines.extend(_capacity_table_lines())
            lines.append("_Full list — Databricks / `capacity.sql`._")
        else:
            lines.extend(_capacity_table_lines())
            lines.append("")
            lines.append(format_role_bucket_section(rows, decision_cfg=cfg, tier=tier))
            lines.append("")
            lines.append(rec)

    if full:
        append_similar_projects_to_lines(
            lines, project_type_tags=project_type_tags, summary=summary
        )

        lines.append("")
        lines.append("\n".join(_followup_block(tier, compact=False)))

    return "\n".join(lines)
