"""
Load Notion-export CSV (People & Tags) and match to Occupation rows by email.

Rules (product):
- Hard exclusions (Comment phrases like do not staff / onboarding) come from live Notion via
  ``staffing_agent.exclusions`` — not from this CSV.
- SO Status: **Primary** = exact **SO** in People & Tags + tier rules. **can be SO** is a **stretch / fallback**
  after confirmed SO in the same pool when tier rules pass — see `so_eligibility_class`.
- Skills: overlap with Phase B `project_type_tags` + thread summary for ranking.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "staffing_csv.yaml"


@dataclass(frozen=True)
class StaffingRecord:
    name: str
    email: str
    job_title: str
    comment: str
    role_tag: str
    so_status: str
    skills: tuple[str, ...]


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def load_staffing_table_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {}
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def default_csv_path() -> Path:
    cfg = load_staffing_table_config()
    rel = (cfg.get("csv_path") or "notion_export/staffing_people_tags_all.csv").strip()
    override = (os.environ.get("STAFFING_PEOPLE_CSV_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _ROOT / "config" / rel


def load_staffing_records(path: Optional[Path] = None) -> dict[str, StaffingRecord]:
    """
    Map normalized email -> StaffingRecord. Last row wins on duplicate emails.
    """
    p = path or default_csv_path()
    if not p.is_file():
        return {}

    out: dict[str, StaffingRecord] = {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}
        rows = list(reader)

    def _col(row: dict[str, str], *names: str) -> str:
        lower = {k.strip(): v for k, v in row.items() if k}
        for n in names:
            if n in lower and lower[n] is not None:
                return str(lower[n]).strip()
            ln = n.lower().strip()
            for k, v in lower.items():
                if k.lower().strip() == ln:
                    return str(v or "").strip()
        return ""

    for row in rows:
        email = _norm_email(_col(row, "Email", "email"))
        if not email or "@" not in email:
            continue
        skills_raw = _col(row, "Skills", "Skills ")
        skills = tuple(s.strip() for s in skills_raw.split(",") if s.strip())
        rec = StaffingRecord(
            name=_col(row, "Name", "name"),
            job_title=_col(row, "Job Title", "Job title"),
            comment=_col(row, "Comment", "comment"),
            role_tag=_col(row, "Role Tag", "Role tag"),
            so_status=_col(row, "SO Status", "SO status"),
            skills=skills,
            email=email,
        )
        out[email] = rec
    return out


def is_so(so_status: str) -> bool:
    """Confirmed accountable SO — exact 'SO' (case-insensitive), not 'can be SO'."""
    return (so_status or "").strip().lower() == "so"


def _so_tier_rules_satisfied(rec: StaffingRecord, tier: int) -> bool:
    if tier in (1, 2):
        return True
    if tier in (3, 4):
        title = (rec.job_title or "").lower()
        is_senior = any(
            x in title for x in ("senior", "sr.", "sr ", "principal", "staff ", "lead ")
        )
        if title.startswith("sr ") or " sr " in title:
            is_senior = True
        parts = [x.strip().upper() for x in re.split(r"[,;/]", rec.role_tag or "") if x.strip()]
        if not parts and (rec.role_tag or "").strip():
            parts = [(rec.role_tag or "").strip().upper()]
        is_dpm = "DPM" in parts
        return is_senior or is_dpm
    return False


def is_so_eligible_for_tier(rec: StaffingRecord, tier: int) -> bool:
    """Confirmed SO only — same tier bar as primary in :func:`so_eligibility_class`."""
    return is_so(rec.so_status) and _so_tier_rules_satisfied(rec, tier)


def so_eligibility_class(
    rec: StaffingRecord,
    tier: int | None,
) -> Literal["ineligible", "primary", "stretch"]:
    """
    SO bench eligibility: **primary** (exact SO), **stretch** (can be SO fallback), or **ineligible**.
    """
    if tier is None or tier not in (1, 2, 3, 4):
        return "ineligible"
    if not is_so_or_can_be_so(rec.so_status):
        return "ineligible"
    if not _so_tier_rules_satisfied(rec, tier):
        return "ineligible"
    if is_so(rec.so_status):
        return "primary"
    return "stretch"


def is_so_or_can_be_so(so_status: str) -> bool:
    """Stretch / ranking: SO or can be SO (do not use for primary SO bucket)."""
    s = (so_status or "").strip().lower()
    if not s:
        return False
    if s == "so":
        return True
    if "can be" in s and "so" in s:
        return True
    return False


def skill_tag_intersection_size(record: StaffingRecord, project_type_tags: list[str]) -> int:
    """|∩| — count of project tags that match CSV skills (substring / token overlap)."""
    if not record.skills or not project_type_tags:
        return 0
    sk_list = [s.strip().lower() for s in record.skills if s.strip()]
    n = 0
    for tag in project_type_tags:
        tl = (tag or "").strip().lower()
        if len(tl) < 2:
            continue
        if any(tl == sl or tl in sl or sl in tl for sl in sk_list):
            n += 1
            continue
        tw = [w for w in tl.split() if len(w) > 2]
        if tw and any(w in sl for sl in sk_list for w in tw):
            n += 1
    return n


def skill_match_score(
    record: StaffingRecord,
    project_type_tags: list[str],
    summary: str,
) -> int:
    """Legacy integer score; prefer :func:`skill_rank_score` for Node 4 ordering."""
    base = skill_tag_intersection_size(record, project_type_tags)
    blob = f"{summary or ''} " + " ".join(project_type_tags or [])
    blob_l = blob.lower()
    score = base * 4
    for tag in project_type_tags:
        tl = (tag or "").strip().lower()
        if len(tl) < 2:
            continue
        if tl in blob_l:
            score += 1
        for sk in record.skills:
            sl = sk.lower()
            if tl in sl or sl in tl:
                score += 4
            else:
                tw = [w for w in tl.split() if len(w) > 2]
                for w in tw:
                    if w in sl:
                        score += 2
    for sk in record.skills:
        sl = sk.lower()
        if len(sl) > 3 and sl in blob_l:
            score += 2
    return score


def skill_rank_score(
    record: StaffingRecord | None,
    project_type_tags: list[str],
    *,
    llm_rerank: float = 0.0,
    summary: str = "",
) -> float:
    """CR-8: |∩| + 0.5 × LLM rerank (rerank clamped to 0..1). ``summary`` unused; kept for call compatibility."""
    _ = summary
    if not record:
        return 0.0
    try:
        rr = float(llm_rerank)
    except (TypeError, ValueError):
        rr = 0.0
    rr = max(0.0, min(1.0, rr))
    return float(skill_tag_intersection_size(record, project_type_tags)) + 0.5 * rr
