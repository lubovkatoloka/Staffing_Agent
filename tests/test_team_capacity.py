import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import CapacityRow, assess
from staffing_agent.staffing_csv import StaffingRecord
from staffing_agent.team_capacity import build_team_capacity_markdown, build_team_capacity_state


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

    parts = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert len(parts) >= 2
    overview, *details = parts
    detail_combined = "\n".join(details)
    assert "TEAM CAPACITY — OVERVIEW" in overview
    assert "TEAM CAPACITY — BY ROLE" in detail_combined
    assert "Team capacity — by role" not in detail_combined  # old title gone
    text = "\n".join(parts)
    assert "Alice SoE" in text
    assert "Bob DPM" in text
    assert "Wally WFM" in text
    assert "Pool right now (FREE / PARTIAL)" in text or "FREE / PARTIAL" in text
    assert "Possible teams NOW" in text
    assert "Tier 2" in text or "T2" in text
    assert "No project staffing snapshot" in text or "snapshot" in overview.lower()
    assert "*Primary:*" not in detail_combined
    assert "*Alternate:*" not in detail_combined
    assert "If we take a project NOW" not in text
    assert "possible teams (independent scenarios" not in text.lower()
    assert "strict FREE only; one person" not in text
    assert "Risks in current pool" not in overview
    assert "Role breakdown follows" not in overview
    assert "_…+" not in overview
    st = build_team_capacity_state(rows, decision_cfg=cfg)
    assert st.names_in_message1.issubset(st.names_in_message2), (
        f"Message 1 names not in role buckets: {st.names_in_message1 - st.names_in_message2}"
    )


def test_team_capacity_detail_splits_into_multiple_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small chunk limit forces several BY ROLE continuation messages."""
    cfg = load_decision_config()
    rows = [
        _person("a@t.com", "Alice SoE", "soe", cfg, _proj("p1", "Pa", tier="Tier 2")),
        _person("b@t.com", "Bob DPM", "dpm", cfg, _proj("p2", "Pb", tier="Tier 2")),
        _person("c@t.com", "Wally WFM", "wfm", cfg, _proj("p3", "Pc", tier="Tier 2")),
    ]
    staffing = {
        "a@t.com": StaffingRecord(
            name="Alice", email="a@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
        "b@t.com": StaffingRecord(
            name="Bob", email="b@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    monkeypatch.setenv("STAFFING_TEAM_CAPACITY_CHUNK_CHARS", "400")
    parts = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert len(parts) >= 3
    assert "TEAM CAPACITY — BY ROLE" in parts[1]
    assert any("continued below" in p for p in parts[2:])


def test_message1_pool_subset_of_message2(monkeypatch: pytest.MonkeyPatch) -> None:
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
    state = build_team_capacity_state(rows, decision_cfg=cfg)
    assert len(state.messages) >= 2
    assert state.names_in_message1.issubset(state.names_in_message2), (
        f"Message 1 has names not in Message 2 buckets: {state.names_in_message1 - state.names_in_message2}"
    )


def test_team_capacity_no_third_message_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-5: full team capacity is exactly two messages; legacy third block removed."""
    cfg = load_decision_config()
    rows = [
        _person("a@t.com", "Alice SoE", "soe", cfg, _proj("p1", "Pa", tier="Tier 2")),
        _person("b@t.com", "Bob DPM", "dpm", cfg, _proj("p2", "Pb", tier="Tier 2")),
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
    parts = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert len(parts) >= 2
    blob = "\n".join(parts)
    assert "If we take a project NOW" not in blob
    assert "independent scenarios" not in blob.lower()
    assert "_Note:_ _No full FREE" not in blob


def test_restricted_subsection_from_people_tags_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    rows = [
        _person("x@t.com", "Xena SoE", "soe", cfg, _proj("p1", "P1", tier="Tier 2")),
    ]
    staffing = {
        "x@t.com": StaffingRecord(
            name="Xena",
            email="x@t.com",
            job_title="",
            comment="Staff only OTS-shaped work for now",
            role_tag="",
            so_status="SO",
            skills=(),
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    _ov, detail = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert "*Restricted*" in detail
    assert "Xena SoE" in detail


def test_word_boundary_project_truncation_in_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    long_name = "MS Copilot Orchestration Omega Studio Pilot Phase"
    rows = [
        _person("a@t.com", "Alice SoE", "soe", cfg, _proj("p1", long_name, tier="Tier 2")),
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
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    _, detail = build_team_capacity_markdown(rows, decision_cfg=cfg)
    assert "Omeg…" not in detail
    assert "Copilot Orchestration Omega" in detail or "Omega Studio" in detail


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
    text = build_team_capacity_markdown(rows, decision_cfg=cfg, only_role="soe")[0]
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
    parts = build_team_capacity_markdown(
        rows,
        decision_cfg=cfg,
        project_staffing_rows=ps_rows,
    )
    text = "\n".join(parts)
    assert "Project staffing snapshot is loaded" in text or "snapshot" in text.lower()
    assert "Hold (snapshot" in text
    assert "hold for Tier < 3" in text


def test_on_pto_today_rendered_in_pto_subsection(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-6: PTO people appear under *PTO today*, not hidden from the role bucket."""
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
    _ov, detail = build_team_capacity_markdown([free_row, on_pto_row], decision_cfg=cfg)
    soe_seg = detail.split("SoE / SSoE", 1)[1].split("DPM", 1)[0]
    assert "Alice Free" in soe_seg
    assert "Bob OnPTO" in soe_seg
    assert "PTO today" in soe_seg
    assert "*FREE*" in soe_seg or "*PARTIAL*" in soe_seg


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
    text = "\n".join(build_team_capacity_markdown([row], decision_cfg=cfg))
    assert "PTO 2026-05-15" in text
    assert "⚠️" not in text


def test_scoping_so_handler_filters_so_bench(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2: pre-sales SO mode drops ≥2 scoping rows or any AT_RISK project."""
    cfg = load_decision_config()
    good = _person(
        "g@t.com",
        "Good SoE",
        "soe",
        cfg,
        _proj("p1", "P1", tier="Tier 2", stage="scoping_solution_design", status="ON_TRACK"),
    )
    at_risk = _person(
        "r@t.com",
        "Risk DPM",
        "dpm",
        cfg,
        _proj("p2", "P2", tier="Tier 2", stage="building", status="AT_RISK"),
    )
    staffing = {
        "g@t.com": StaffingRecord(
            name="Good", email="g@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
        "r@t.com": StaffingRecord(
            name="Risk", email="r@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    text_all = "\n".join(
        build_team_capacity_markdown([good, at_risk], decision_cfg=cfg, only_role="so")
    )
    assert "Good SoE" in text_all
    assert "Risk DPM" in text_all

    text_s2 = "\n".join(
        build_team_capacity_markdown(
            [good, at_risk],
            decision_cfg=cfg,
            only_role="so",
            scoping_so_handler=True,
        )
    )
    assert "Good SoE" in text_s2
    assert "Risk DPM" not in text_s2


def test_only_role_compact_shortlist_has_primary_and_alternates(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_decision_config()
    rows = [
        _person("a@t.com", "A1", "soe", cfg, _proj("p1", "P1", tier="Tier 2")),
        _person("b@t.com", "B2", "soe", cfg, _proj("p2", "P2", tier="Tier 2")),
        _person("c@t.com", "C3", "soe", cfg, _proj("p3", "P3", tier="Tier 2")),
    ]
    staffing = {
        "a@t.com": StaffingRecord(
            name="A1", email="a@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
        "b@t.com": StaffingRecord(
            name="B2", email="b@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
        "c@t.com": StaffingRecord(
            name="C3", email="c@t.com", job_title="", comment="", role_tag="", so_status="SO", skills=()
        ),
    }
    monkeypatch.setattr("staffing_agent.team_capacity.load_staffing_records", lambda: staffing)
    text = build_team_capacity_markdown(
        rows,
        decision_cfg=cfg,
        only_role="soe",
        role_shortlist_compact=True,
    )[0]
    assert "*Primary*" in text
    assert "*Alternates*" in text
    assert "A1" in text
