from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import CapacityRow, assess
from staffing_agent.node4_recommendation import build_project_recommendation_markdown
from staffing_agent.staffing_csv import StaffingRecord


def _proj(
    pid: str,
    pname: str,
    *,
    tier: str = "Tier 3",
    stage: str = "building",
    status: str = "ON_TRACK",
) -> CapacityRow:
    return CapacityRow(project_id=pid, project_name=pname, tier=tier, stage=stage, status=status)


def _person(email: str, name: str, role: str, cfg, tier_ctx: int, *projects: CapacityRow) -> dict:
    tw = cfg.get("tier_weights") or {}
    npw = float(tw.get(f"Tier {tier_ctx}", 1.0))
    v = assess(
        list(projects),
        on_pto_today=False,
        pto_upcoming=None,
        in_hard_exclude=False,
        new_project_weight=npw,
        cfg=cfg,
    )
    return {
        "user_name": name,
        "user_email": email,
        "project_role": role,
        "_capacity_verdict": v,
        "_capacity_rows": tuple(projects),
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
    }
    rows = [
        _person(
            "first@test.com",
            "FirstPick",
            "dpm",
            cfg,
            2,
            _proj("p1", "A", tier="Tier 2"),
        ),
        _person(
            "second@test.com",
            "SecondFree",
            "soe",
            cfg,
            2,
            _proj("p2", "B", tier="Tier 2"),
        ),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing
    )
    assert "*SO Recommendations*" in text
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

    def _p3(email: str, name: str, role: str, tier_load: str):
        return _person(email, name, role, cfg, 3, _proj(f"id-{email}", "Px", tier=tier_load))

    rows = [
        _p3("d@t.com", "Dpm Lead", "dpm", "Tier 2"),
        _p3("s@t.com", "Soe Dev", "soe", "Tier 3"),
        _p3("w@t.com", "Wfm Ops", "wfm", "Tier 3"),
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
    assert "Dpm Lead" in text
    assert "Wfm Ops" in text


def test_tier3_so_primary_email_excluded_from_soe_slice():
    """SO slot winner email never repeats under SoE Recommendations (primary-only exclusion rule)."""
    cfg = load_decision_config()
    staffing = {
        "charlie@t.com": _so("charlie@t.com"),
        "eddie@t.com": _so("eddie@t.com"),
        "dana@t.com": _so("dana@t.com"),
    }
    rows = [
        _person("charlie@t.com", "Charlie Dpm", "dpm", cfg, 3, _proj("p1", "Light", tier="Tier 3")),
        _person(
            "eddie@t.com",
            "Eddie Dpm",
            "dpm",
            cfg,
            3,
            _proj("e1", "Heavy A", tier="Tier 3"),
            _proj("e2", "Heavy B", tier="Tier 3"),
        ),
        _person("dana@t.com", "Dana Soe", "soe", cfg, 3, _proj("d1", "SoeProj", tier="Tier 3")),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=3, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "*SO Recommendations*" in text and "*SoE Recommendations*" in text
    _, after_soe_header = text.split("*SoE Recommendations*", 1)
    assert "Charlie Dpm" not in after_soe_header
    assert "Eddie Dpm" not in after_soe_header
    assert "Dana Soe" in after_soe_header


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

    def _one(email: str, name: str, role: str):
        return _person(email, name, role, cfg, 3, _proj(email, "Px", tier="Tier 2"))

    rows = [
        _one("a@t.com", "Dpm A", "dpm"),
        _one("b@t.com", "Dpm B", "dpm"),
        _one("c@t.com", "Dpm C", "dpm"),
        _one("busy@t.com", "Busy SoE", "soe"),
        _one("free@t.com", "Free SoE", "soe"),
    ]
    ps_rows = [{"name": f"O{i}", "status": "ON_TRACK", "stage": "s", "soe": "Busy SoE"} for i in range(3)]
    text = build_project_recommendation_markdown(
        rows,
        tier=3,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        detail="minimal",
        project_staffing_rows=ps_rows,
    )
    soe_seg = text.split("*SoE Recommendations*", 1)[1].split("*WFM Recommendations*", 1)[0]
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
        _person("heavy@t.com", "Heavy DPM", "dpm", cfg, 3, _proj("h", "H", tier="Tier 2")),
        _person("light@t.com", "Light DPM", "dpm", cfg, 3, _proj("l", "L", tier="Tier 2")),
    ]
    ps_rows = [{"name": f"Ord{i}", "status": "ON_TRACK", "stage": "building", "dpm": "Heavy DPM"} for i in range(3)]
    text = build_project_recommendation_markdown(
        rows,
        tier=3,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        detail="minimal",
        project_staffing_rows=ps_rows,
    )
    so_seg = text.split("*SO Recommendations*", 1)[1].split("*SoE Recommendations*", 1)[0]
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
        _person("d@t.com", "Dpm", "dpm", cfg, 3, _proj("1", "P", tier="Tier 2")),
        _person("s@t.com", "Soe", "soe", cfg, 3, _proj("2", "Q", tier="Tier 3")),
        _person("w@t.com", "Wfm", "wfm", cfg, 3, _proj("3", "R", tier="Tier 3")),
    ]
    text = build_project_recommendation_markdown(
        rows, tier=3, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "*SO Recommendations*" in text
    assert "*SoE Recommendations*" in text
    assert "*WFM Recommendations*" in text
    assert "_Why:_" not in text
    assert "Dpm" in text or "Soe" in text


def test_tier_none_asks_for_tier():
    cfg = load_decision_config()
    text = build_project_recommendation_markdown(
        [_person("x@test.com", "X", "soe", cfg, 2, _proj("z", "Z"))],
        tier=None,
        decision_cfg=cfg,
        staffing_by_email={"x@test.com": _so("x@test.com")},
    )
    assert "Phase B" in text or "Tier" in text


def test_executor_excluded_from_pick():
    cfg = load_decision_config()
    staffing = {
        "exec@test.com": _so("exec@test.com", so_status="Executor"),
        "ok@test.com": _so("ok@test.com", so_status="SO"),
    }
    rows = [
        _person("exec@test.com", "Exec", "soe", cfg, 2, _proj("e", "E", tier="Tier 2")),
        _person("ok@test.com", "Ok", "soe", cfg, 2, _proj("o", "O", tier="Tier 2")),
    ]
    text = build_project_recommendation_markdown(rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing)
    assert "*SO Recommendations*" in text
    so_seg = text.split("*SO Recommendations*", 1)[1].split("*WFM Recommendations*", 1)[0]
    assert "Ok" in so_seg
    assert "Exec" not in so_seg


def test_skill_ranking_with_tags():
    cfg = load_decision_config()
    staffing = {
        "a@test.com": _so("a@test.com", skills=("TTS", "Evals")),
        "b@test.com": _so("b@test.com", skills=("Coding",)),
    }
    rows = [
        _person("b@test.com", "B", "soe", cfg, 2, _proj("b", "B", tier="Tier 2")),
        _person("a@test.com", "A", "soe", cfg, 2, _proj("a", "A", tier="Tier 2")),
    ]
    text = build_project_recommendation_markdown(
        rows,
        tier=2,
        decision_cfg=cfg,
        staffing_by_email=staffing,
        project_type_tags=["TTS", "Evals"],
        summary="TTS eval",
    )
    assert "A" in text
    so_seg = text.split("*SO Recommendations*", 1)[1].split("*WFM Recommendations*", 1)[0]
    assert so_seg.index("A") < so_seg.index("B")


def test_upcoming_pto_renders_marker_in_recommendation():
    cfg = load_decision_config()
    staffing = {"a@t.com": _so("a@t.com")}
    rows = [_person("a@t.com", "Alice", "soe", cfg, 2, _proj("p1", "P1", tier="Tier 2"))]
    rows[0]["_capacity_verdict"] = assess(
        list(rows[0]["_capacity_rows"]),
        on_pto_today=False,
        pto_upcoming=("2026-05-15", "2026-05-22"),
        in_hard_exclude=False,
        new_project_weight=float((cfg.get("tier_weights") or {}).get("Tier 2", 1.0)),
        cfg=cfg,
    )
    text = build_project_recommendation_markdown(
        rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "⚠️ PTO 2026-05-15" in text
    assert "Alice" in text


def test_on_pto_today_excluded_from_picks():
    cfg = load_decision_config()
    staffing = {"a@t.com": _so("a@t.com"), "b@t.com": _so("b@t.com")}
    tw = cfg.get("tier_weights") or {}
    npw = float(tw.get("Tier 2", 1.0))
    free_row = _person("a@t.com", "Alice", "soe", cfg, 2, _proj("p1", "P", tier="Tier 2"))
    on_pto_row = _person("b@t.com", "Bob OnPTO", "soe", cfg, 2)
    on_pto_row["_capacity_verdict"] = assess(
        [],
        on_pto_today=True,
        pto_upcoming=None,
        in_hard_exclude=False,
        new_project_weight=npw,
        cfg=cfg,
    )
    text = build_project_recommendation_markdown(
        [on_pto_row, free_row], tier=2, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "Alice" in text
    so_seg = text.split("*SO Recommendations*", 1)[1]
    assert "Bob OnPTO" not in so_seg


def test_combined_risk_and_pto_markers_capped_at_two():
    cfg = load_decision_config()
    staffing = {"a@t.com": _so("a@t.com")}
    rows = [
        _person(
            "a@t.com",
            "Alice",
            "soe",
            cfg,
            2,
            _proj("p1", "P1", tier="Tier 2", stage="discovery", status="BEHIND"),
        )
    ]
    rows[0]["_capacity_verdict"] = assess(
        list(rows[0]["_capacity_rows"]),
        on_pto_today=False,
        pto_upcoming=("2026-05-15", "2026-05-22"),
        in_hard_exclude=False,
        new_project_weight=float((cfg.get("tier_weights") or {}).get("Tier 2", 1.0)),
        cfg=cfg,
    )
    text = build_project_recommendation_markdown(
        rows, tier=2, decision_cfg=cfg, staffing_by_email=staffing, detail="minimal"
    )
    assert "⚠️ BEHIND" in text
    assert "⚠️ PTO 2026-05-15" in text

