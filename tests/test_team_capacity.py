import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.staffing_csv import StaffingRecord
from staffing_agent.team_capacity import build_team_capacity_markdown


def _row(
    email: str,
    name: str,
    role: str,
    occ: float,
) -> dict:
    return {
        "user_email": email,
        "user_name": name,
        "project_role": role,
        "occupation": occ,
    }


def test_build_team_capacity_sections_and_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _row("a@t.com", "Alice SoE", "soe", 0.1),
        _row("b@t.com", "Bob DPM", "dpm", 0.15),
        _row("c@t.com", "Wally WFM", "wfm", 0.2),
        _row("d@t.com", "Quinn QM", "qm", 0.1),
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

    text = build_team_capacity_markdown(rows)
    assert "Team capacity" in text
    assert "Alice SoE" in text
    assert "Bob DPM" in text
    assert "Wally WFM" in text
    assert "Tier 1 — scoping" in text
    assert "Tier 2" in text
    assert "No project staffing snapshot" in text


def test_team_capacity_snapshot_hold_for_three_plus_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    """SO list (tier=2 gates): 3+ stab orders → hold, same as Node 4."""
    rows = [
        _row("n@t.com", "Nina Erlich", "soe", 0.3),
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
        decision_cfg=load_decision_config(),
        project_staffing_rows=ps_rows,
    )
    assert "project_staffing.sql" in text
    assert "Hold (snapshot" in text
    assert "hold for Tier < 3" in text
