import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import CapacityRow, assess
from staffing_agent.staffing_csv import StaffingRecord
from staffing_agent.team_capacity import build_team_capacity_markdown


def _proj(
    pid: str = "p",
    pname: str = "P",
    *,
    tier: str = "Tier 3",
    stage: str = "building",
    status: str = "ON_TRACK",
) -> CapacityRow:
    return CapacityRow(project_id=pid, project_name=pname, tier=tier, stage=stage, status=status)


def _person(email: str, name: str, role: str, cfg, *projects: CapacityRow) -> dict:
    v = assess(
        list(projects),
        on_pto_today=False,
        pto_upcoming=None,
        in_hard_exclude=False,
        new_project_weight=0.0,
        cfg=cfg,
    )
    return {
        "user_email": email,
        "user_name": name,
        "project_role": role,
        "_capacity_verdict": v,
        "_capacity_rows": tuple(projects),
    }


def test_build_team_capacity_sections_and_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    rows = [
        _person("a@t.com", "Alice SoE", "soe", cfg, _proj("p1", "Pa", tier="Tier 2")),
        _person("b@t.com", "Bob DPM", "dpm", cfg, _proj("p2", "Pb", tier="Tier 2")),
        _person("c@t.com", "Wally WFM", "wfm", cfg, _proj("p3", "Pc", tier="Tier 2")),
        _person("d@t.com", "Quinn QM", "qm", cfg, _proj("p4", "Pd", tier="Tier 2")),
    ]
    staffing = {
        "a@t.com": StaffingRecord(
            name="Alice",
            email="a@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
        "b@t.com": StaffingRecord(
            name="Bob",
            email="b@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)

    text = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert "Team capacity" in text
    assert "Alice SoE" in text
    assert "Bob DPM" in text
    assert "Wally WFM" in text
    assert "Tier 1 — scoping" in text
    assert "Tier 2" in text
    assert "No project staffing snapshot" in text
    assert "*Primary:*" in text
    assert "*Alternate:*" in text


def test_only_role_soe_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    rows = [
        _person("a@t.com", "Alice SoE", "soe", cfg, _proj("p1", "P1", tier="Tier 2")),
        _person("b@t.com", "Bob DPM", "dpm", cfg, _proj("p2", "P2", tier="Tier 2")),
    ]
    staffing = {
        "a@t.com": StaffingRecord(
            name="Alice",
            email="a@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
        "b@t.com": StaffingRecord(
            name="Bob",
            email="b@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    text = build_team_capacity_markdown(rows, decision_cfg=cfg, only_role="soe")
    assert "role shortlist" in text.lower()
    assert "Alice SoE" in text
    assert "Bob DPM" not in text


def test_team_capacity_snapshot_hold_for_three_plus_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    """SO list (tier=2 gates): 3+ stab orders → hold, same as Node 4."""
    cfg = load_decision_config()
    rows = [
        _person("n@t.com", "Nina Erlich", "soe", cfg, _proj("px", "Px", tier="Tier 2")),
    ]
    staffing = {
        "n@t.com": StaffingRecord(
            name="Nina",
            email="n@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    ps_rows = [
        {"stage": "stabilisation_delivery", "status": "ON_TRACK", "soe": "Nina Erlich"},
        {"stage": "stabilisation_delivery", "status": "ON_TRACK", "soe": "Nina Erlich"},
        {"stage": "stabilisation_delivery", "status": "ON_TRACK", "soe": "Nina Erlich"},
    ]
    text = build_team_capacity_markdown(
        rows,
        decision_cfg=cfg,
        project_staffing_rows=ps_rows,
    )
    assert "project_staffing.sql" in text
    assert "Hold (snapshot" in text
    assert "hold for Tier < 3" in text


def test_on_pto_today_not_in_free_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    tw = cfg.get("tier_weights") or {}
    npw = float(tw.get("Tier 2", 1.0))
    free_row = _person("a@t.com", "Alice Free", "soe", cfg, _proj("p1", "P", tier="Tier 2"))
    on_pto_row = {
        "user_email": "b@t.com",
        "user_name": "Bob OnPTO",
        "project_role": "soe",
        "_capacity_verdict": assess(
            [],
            on_pto_today=True,
            pto_upcoming=None,
            in_hard_exclude=False,
            new_project_weight=npw,
            cfg=cfg,
        ),
        "_capacity_rows": (),
    }
    staffing = {
        "a@t.com": StaffingRecord(
            name="Alice",
            email="a@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
        "b@t.com": StaffingRecord(
            name="Bob",
            email="b@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    text = build_team_capacity_markdown([free_row, on_pto_row], decision_cfg=cfg)
    soe_seg = text.split("SoE / SSoE", 1)[1].split("DPM", 1)[0]
    assert "Alice Free" in soe_seg
    assert "Bob OnPTO" not in soe_seg
    assert "PTO today: 1" in soe_seg


def test_upcoming_pto_marker_in_team_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    row = _person("a@t.com", "Alice", "soe", cfg, _proj("p1", "P", tier="Tier 2"))
    row["_capacity_verdict"] = assess(
        list(row["_capacity_rows"]),
        on_pto_today=False,
        pto_upcoming=("2026-05-15", "2026-05-22"),
        in_hard_exclude=False,
        new_project_weight=0.0,
        cfg=cfg,
    )
    staffing = {
        "a@t.com": StaffingRecord(
            name="Alice",
            email="a@t.com",
            job_title="",
            comment="",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    text = build_team_capacity_markdown([row], decision_cfg=cfg)
    assert "⚠️ PTO 2026-05-15" in text

