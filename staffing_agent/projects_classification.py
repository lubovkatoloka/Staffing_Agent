"""
Projects & Offers Classification CSV — similar past projects by tags and summary (Phase B).

Without Notion API: place the export in config/ (see projects_classification.yaml).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CFG = _ROOT / "config" / "projects_classification.yaml"


def _load_yaml() -> dict[str, Any]:
    if not _CFG.is_file():
        return {}
    with open(_CFG, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def default_csv_path() -> Optional[Path]:
    cfg = _load_yaml()
    rel = (cfg.get("csv_path") or "notion_export/projects_offers_classification_0.csv").strip()
    override = (os.environ.get("STAFFING_PROJECTS_CLASSIFICATION_CSV_PATH") or "").strip()
    if override:
        p = Path(override).expanduser()
        return p if p.is_file() else None
    p = _ROOT / "config" / rel
    return p if p.is_file() else None


def _col(row: dict[str, str], *names: str) -> str:
    for n in names:
        for k, v in row.items():
            if k and k.strip().lower() == n.strip().lower():
                return str(v or "").strip()
    return ""


def load_classification_rows(path: Optional[Path] = None) -> list[dict[str, str]]:
    p = path or default_csv_path()
    if not p or not p.is_file():
        return []
    out: list[dict[str, str]] = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return out


def _row_blob(row: dict[str, str]) -> str:
    parts = [
        _col(row, "Capability Domain"),
        _col(row, "Domain Specialization"),
        _col(row, "Notes"),
        _col(row, "Project Name"),
        _col(row, "Client"),
        _col(row, "Training Methodology"),
        _col(row, "Revenue Stream"),
    ]
    return " ".join(parts).lower()


def _score_row(row: dict[str, str], tags: list[str], summary: str) -> int:
    blob = _row_blob(row)
    summary_l = (summary or "").lower()
    blob_full = f"{blob} {summary_l}"
    score = 0
    for tag in tags:
        tl = (tag or "").strip().lower()
        if len(tl) < 2:
            continue
        if tl in blob_full:
            score += 6
        for w in tl.replace("&", " ").split():
            w = w.strip()
            if len(w) > 2 and w in blob_full:
                score += 3
    for raw in summary.split():
        wl = raw.strip(".,;:!\"'()[]").lower()
        if len(wl) > 3 and wl in blob:
            score += 2
    return score


def build_similar_projects_markdown(
    project_type_tags: list[str],
    summary: str,
    *,
    max_similar: Optional[int] = None,
) -> str:
    """
    Top similar rows from classification CSV; empty string if file missing or nothing to match.
    """
    cfg = _load_yaml()
    n = max_similar if max_similar is not None else int(cfg.get("max_similar") or 5)

    tags = [t for t in (project_type_tags or []) if (t or "").strip()]
    summary = summary or ""
    if not tags and len(summary.strip()) < 8:
        return ""

    rows = load_classification_rows()
    if not rows:
        return ""

    scored: list[tuple[int, dict[str, str]]] = []
    for row in rows:
        s = _score_row(row, tags, summary)
        scored.append((s, row))

    scored.sort(key=lambda it: (-it[0], _col(it[1], "Project Name")))
    positive = [(s, r) for s, r in scored if s > 0][:n]

    lines: list[str] = [
        "*Similar projects (Offers classification)* "
        "_overlap of Phase B tags with Capability / Notes / name._",
    ]
    if not positive:
        lines.append(
            "_No rows with a strong match — broaden `project_type_tags` or summary in Phase B._"
        )
        return "\n".join(lines)

    for _, row in positive:
        pname = _col(row, "Project Name") or "—"
        client = _col(row, "Client") or "—"
        cap = _col(row, "Capability Domain") or "—"
        clip = pname if len(pname) <= 120 else pname[:117] + "…"
        lines.append(f"• *{client}* — {clip}")
        lines.append(f"  _Capability:_ {cap[:200]}{'…' if len(cap) > 200 else ''}_")

    lines.append("_Source: Projects & Offers Classification export (CSV in `config/`)._")
    return "\n".join(lines)


def append_similar_projects_to_lines(
    lines: list[str],
    *,
    project_type_tags: Optional[list[str]],
    summary: str,
) -> None:
    block = build_similar_projects_markdown(project_type_tags or [], summary or "")
    if block:
        lines.append("")
        lines.append(block)
