"""Slack-facing string helpers (truncation, band labels, project status words)."""

from __future__ import annotations

from collections.abc import Sequence

from staffing_agent.decision.capacity import CapacityRow
from staffing_agent.decision.enums import Band


def truncate_at_word_boundary(text: str, max_len: int, *, suffix: str = "…") -> str:
    """Truncate without cutting mid-word (prefer last full word; spec PR-4)."""
    s = " ".join((text or "").split()).strip() or "?"
    if len(s) <= max_len:
        return s
    budget = max_len - len(suffix)
    if budget < 8:
        return s[:max_len]
    chunk = s[:budget].rstrip()
    if " " not in chunk:
        return chunk + suffix
    return chunk.rsplit(" ", 1)[0].rstrip() + suffix


def band_label_for_slack(band: Band) -> str:
    """Display band; AT_CAP shown as OVER_CAP (readability spec)."""
    if band == Band.AT_CAP:
        return "OVER_CAP"
    return band.value


def project_status_word(status: str) -> str | None:
    """Deviation-only status token. ON_TRACK / empty → None (omitted in lists)."""
    u = (status or "").strip().upper()
    if u in ("", "ON_TRACK"):
        return None
    return u


def compress_slash(labels: list[str]) -> str:
    """Display tier groups: T2, T3, T4 → ``T2/T3/T4`` (sorted)."""
    order = []
    seen: set[str] = set()
    for raw in labels:
        x = (raw or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        order.append(x)

    def _sort_key(s: str) -> tuple[int, str]:
        if s == "T1":
            return (10, s)
        if s.startswith("T") and s[1:].isdigit():
            return (20 + int(s[1:]), s)
        return (999, s)

    order.sort(key=_sort_key)
    return "/".join(order)


def project_status_risk_rank(status: str) -> int:
    """Sort riskier project health first (PR-6 OVER_CAP project list)."""
    u = (status or "").strip().upper()
    if u == "BEHIND":
        return 0
    if u == "AT_RISK":
        return 1
    if u.startswith("BLOCKED"):
        return 2
    return 3


def _stage_slack_short(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "_")
    m = {
        "building": "build",
        "stabilisation_delivery": "stab",
        "scoping_solution_design": "scoping",
        "discovery": "disc",
        "close_out_retrospective": "close-out",
    }
    return m.get(key, key.replace("_", "-")[:12])


def _tier_sort_num(tier: str) -> int:
    t = (tier or "").replace("Tier", "").strip()
    if t.isdigit():
        return int(t)
    return 99


def risk_breakdown_summary(rows: Sequence[CapacityRow]) -> str:
    """Compact deviation counts, e.g. ``BEHIND 2 · AT_RISK 1`` (omits ON_TRACK)."""
    counts: dict[str, int] = {}
    for r in rows:
        w = project_status_word(r.status or "")
        if not w:
            continue
        counts[w] = counts.get(w, 0) + 1
    if not counts:
        return ""
    preferred = ("BEHIND", "AT_RISK")
    bits: list[str] = []
    used: set[str] = set()
    for k in preferred:
        if k in counts:
            bits.append(f"{k} {counts[k]}")
            used.add(k)
    for k in sorted(counts.keys()):
        if k not in used:
            bits.append(f"{k} {counts[k]}")
    return " · ".join(bits)


def truncate_overcap_projects(
    rows: Sequence[CapacityRow],
    *,
    top_n: int = 3,
    name_max_len: int = 48,
) -> tuple[str, int]:
    """Top ``top_n`` projects by risk (then tier, name); return (formatted.join, rest count)."""
    crs = list(rows)
    crs.sort(
        key=lambda cr: (
            project_status_risk_rank(cr.status or ""),
            _tier_sort_num(cr.tier or ""),
            (cr.project_name or cr.project_id or "").lower(),
        )
    )
    if not crs:
        return "", 0
    shown = crs[:top_n]
    rest = max(0, len(crs) - top_n)
    parts: list[str] = []
    for cr in shown:
        pname = truncate_at_word_boundary(cr.project_name or cr.project_id or "?", name_max_len)
        tier_bit = (cr.tier or "").replace("Tier ", "T").strip() or "T?"
        st = _stage_slack_short(cr.stage or "")
        stat_word = project_status_word(cr.status or "")
        stat_seg = f", {stat_word}" if stat_word else ""
        parts.append(f"{pname} ({tier_bit} {st}{stat_seg})")
    return "; ".join(parts), rest
