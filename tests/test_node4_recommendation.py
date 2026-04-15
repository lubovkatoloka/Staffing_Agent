from staffing_agent.config_loader import load_decision_config
from staffing_agent.node4_recommendation import build_project_recommendation_markdown
from staffing_agent.staffing_csv import StaffingRecord


def _r(name: str, email: str, role: str, occ: float) -> dict:
    return {
        "user_name": name,
        "user_email": email,
        "project_role": role,
        "occupation": occ,
    }


def _so(email: str, so_status: str = "SO", skills: tuple[str, ...] = (), comment: str = "") -> StaffingRecord:
    return StaffingRecord(
        name=email.split("@")[0],
        email=email,
        job_title="",
        comment=comment,
        role_tag="",
        so_status=so_status,
        skills=skills,
    )


def test_tier2_primary_is_free_lowest_occupation():
    cfg = load_decision_config()
    staffing = {
        "first@test.com": _so("first@test.com"),
        "second@test.com": _so("second@test.com"),
        "unver@test.com": _so("unver@test.com"),
    }
    rows = [
        _r("Unver", "unver@test.com", "soe", 0.0),
        _r("FirstPick", "first@test.com", "dpm", 0.05),
        _r("SecondFree", "second@test.com", "soe", 0.2),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing
    )
    assert "First pick" in text
    assert "FirstPick" in text
    idx_first = text.index("FirstPick")
    idx_second = text.index("SecondFree")
    assert idx_first < idx_second


def test_tier3_shows_on_active_orders_when_snapshot_provided():
    cfg = load_decision_config()
    staffing = {
        "d@t.com": _so("d@t.com"),
        "s@t.com": _so("s@t.com"),
        "w@t.com": _so("w@t.com"),
    }
    rows = [
        _r("Dpm Lead", "d@t.com", "dpm", 0.05),
        _r("Soe Dev", "s@t.com", "soe", 0.1),
        _r("Wfm Ops", "w@t.com", "wfm", 0.15),
    ]
    ps_rows = [
        {
            "name": "Northwind Pilot",
            "client_name": "Contoso",
            "stage": "discovery",
            "status": "ON_TRACK",
            "dpm": "Dpm Lead",
        },
        {
            "name": "Fabrikam Ops",
            "client_name": "Fabrikam",
            "stage": "stabilisation_delivery",
            "status": "BEHIND",
            "wfm": "Wfm Ops",
        },
    ]
    text = build_project_recommendation_markdown(
        rows,
        tier=3,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        detail="minimal",
        project_staffing_rows=ps_rows,
    )
    assert "_On active orders:_" in text
    assert "Northwind Pilot" in text
    assert "Fabrikam Ops" in text


def test_tier3_same_person_not_listed_under_so_and_soe():
    """Node 4: distinct seats — anyone in the SO shortlist is omitted from the SoE list."""
    cfg = load_decision_config()
    staffing = {
        "a@t.com": _so("a@t.com"),
        "b@t.com": _so("b@t.com"),
    }
    rows = [
        _r("Amy DPM", "a@t.com", "dpm", 0.05),
        _r("Bob Soe", "b@t.com", "soe", 0.06),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=3, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    _, after_soe_header = text.split("*SoE*", 1)
    assert "Bob Soe" not in after_soe_header


def test_tier3_soe_skips_when_too_many_parallel_orders():
    """SoE slot uses exclude_soe_if_active_orders_gte from config (same idea as SO)."""
    cfg = load_decision_config()
    staffing = {
        "a@t.com": _so("a@t.com"),
        "b@t.com": _so("b@t.com"),
        "c@t.com": _so("c@t.com"),
        "busy@t.com": _so("busy@t.com"),
        "free@t.com": _so("free@t.com"),
    }
    rows = [
        _r("Dpm A", "a@t.com", "dpm", 0.01),
        _r("Dpm B", "b@t.com", "dpm", 0.02),
        _r("Dpm C", "c@t.com", "dpm", 0.03),
        _r("Busy SoE", "busy@t.com", "soe", 0.1),
        _r("Free SoE", "free@t.com", "soe", 0.2),
    ]
    ps_rows = [
        {"name": f"O{i}", "status": "ON_TRACK", "stage": "s", "soe": "Busy SoE"}
        for i in range(3)
    ]
    text = build_project_recommendation_markdown(
        rows,
        tier=3,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        detail="minimal",
        project_staffing_rows=ps_rows,
    )
    soe_seg = text.split("*SoE*", 1)[1].split("*WFM / WFC*", 1)[0]
    assert "Busy SoE" not in soe_seg
    assert "Free SoE" in soe_seg


def test_tier3_so_slot_skips_when_too_many_active_orders():
    """SO accountability: exclude from SO shortlist if ≥N concurrent orders in project_staffing snapshot."""
    cfg = load_decision_config()
    staffing = {
        "heavy@t.com": _so("heavy@t.com"),
        "light@t.com": _so("light@t.com"),
    }
    rows = [
        _r("Heavy DPM", "heavy@t.com", "dpm", 0.04),
        _r("Light DPM", "light@t.com", "dpm", 0.08),
    ]
    ps_rows = [
        {"name": f"Ord{i}", "status": "ON_TRACK", "stage": "building", "dpm": "Heavy DPM"}
        for i in range(3)
    ]
    text = build_project_recommendation_markdown(
        rows,
        tier=3,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        detail="minimal",
        project_staffing_rows=ps_rows,
    )
    so_seg = text.split("*SO (SSoE or DPM)*", 1)[1].split("*SoE*", 1)[0]
    assert "Heavy DPM" not in so_seg
    assert "Light DPM" in so_seg


def test_tier3_has_so_soe_wfm_sections():
    cfg = load_decision_config()
    staffing = {
        "d@t.com": _so("d@t.com"),
        "s@t.com": _so("s@t.com"),
        "w@t.com": _so("w@t.com"),
    }
    rows = [
        _r("Dpm", "d@t.com", "dpm", 0.05),
        _r("Soe", "s@t.com", "soe", 0.1),
        _r("Wfm", "w@t.com", "wfm", 0.15),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=3, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "*SO (SSoE or DPM)*" in text
    assert "*SoE*" in text
    assert "*WFM / WFC*" in text
    assert "_Why:_" in text
    assert "Dpm" in text or "Soe" in text


def test_tier_none_asks_for_tier():
    cfg = load_decision_config()
    text = build_project_recommendation_markdown(
        [_r("X", "x@test.com", "soe", 0.1)],
        tier=None,
        decision_cfg=cfg,
        staffing_by_email={"x@test.com": _so("x@test.com")},
    )
    assert "Phase B" in text or "Tier" in text


def test_all_unverified_still_lists_names():
    cfg = load_decision_config()
    staffing = {"a@test.com": _so("a@test.com"), "b@test.com": _so("b@test.com")}
    rows = [
        _r("A", "a@test.com", "soe", 0.0),
        _r("B", "b@test.com", "dpm", 0.0),
    ]
    text = build_project_recommendation_markdown(rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing)
    assert "UNVERIFIED" in text
    assert "A" in text or "B" in text


def test_unverified_listed_even_when_many_free():
    staffing = {f"{i}@t.com": _so(f"{i}@t.com") for i in range(5)}
    rows = [
        _r("U1", "0@t.com", "soe", 0.0),
        _r("F1", "1@t.com", "dpm", 0.05),
        _r("F2", "2@t.com", "soe", 0.1),
        _r("F3", "3@t.com", "soe", 0.15),
        _r("F4", "4@t.com", "dpm", 0.2),
    ]
    cfg = load_decision_config()
    text = build_project_recommendation_markdown(rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing)
    assert "U1" in text
    assert "UNVERIFIED" in text


def test_executor_excluded_from_pick():
    cfg = load_decision_config()
    staffing = {
        "exec@test.com": _so("exec@test.com", so_status="Executor"),
        "ok@test.com": _so("ok@test.com", so_status="SO"),
    }
    rows = [
        _r("Exec", "exec@test.com", "soe", 0.1),
        _r("Ok", "ok@test.com", "soe", 0.15),
    ]
    text = build_project_recommendation_markdown(rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing)
    assert "First pick" in text
    assert "Ok" in text
    assert "not SO" in text or "Executor" in text or "responsible" in text


def test_skill_ranking_with_tags():
    cfg = load_decision_config()
    staffing = {
        "a@test.com": _so("a@test.com", skills=("TTS", "Evals")),
        "b@test.com": _so("b@test.com", skills=("Coding",)),
    }
    rows = [
        _r("B", "b@test.com", "soe", 0.1),
        _r("A", "a@test.com", "soe", 0.1),
    ]
    text = build_project_recommendation_markdown(
        rows,
        tier=2,
        decision_cfg=cfg,
        project_type_tags=["TTS", "Evals"],
        summary="TTS eval",
        staffing_by_email=staffing,
    )
    assert "A" in text
    ia = text.index("First pick")
    rest = text[ia : ia + 200]
    assert "A" in rest or "a@" in text
