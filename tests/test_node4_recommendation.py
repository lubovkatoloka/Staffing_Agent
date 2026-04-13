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
    assert "Первый выбор" in text
    assert "FirstPick" in text
    idx_first = text.index("FirstPick")
    idx_second = text.index("SecondFree")
    assert idx_first < idx_second


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
    assert "Первый выбор" in text
    assert "Ok" in text
    assert "не SO" in text or "Executor" in text or "responsible" in text


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
    ia = text.index("Первый выбор")
    rest = text[ia : ia + 200]
    assert "A" in rest or "a@" in text
