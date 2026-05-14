from staffing_agent.staffing_csv import (
    StaffingRecord,
    is_so,
    is_so_eligible_for_tier,
    is_so_or_can_be_so,
    skill_match_score,
    skill_rank_score,
    skill_tag_intersection_size,
    so_eligibility_class,
)


def test_is_so_strict():
    assert is_so("SO") is True
    assert is_so(" so ") is True
    assert is_so("can be SO") is False
    assert is_so("Executor") is False
    assert is_so("") is False


def test_is_so_or_can_be_so_stretch():
    assert is_so_or_can_be_so("SO") is True
    assert is_so_or_can_be_so("can be SO") is True
    assert is_so_or_can_be_so("Executor") is False
    assert is_so_or_can_be_so("") is False


def _rec(
    *,
    so_status: str = "SO",
    job_title: str = "",
    role_tag: str = "",
) -> StaffingRecord:
    return StaffingRecord(
        name="x",
        email="x@t.com",
        job_title=job_title,
        comment="",
        role_tag=role_tag,
        so_status=so_status,
        skills=(),
    )


def test_is_so_eligible_for_tier_t12_any_confirmed_so():
    r = _rec(so_status="SO", job_title="Software Engineer", role_tag="SSOE+SOE")
    assert is_so_eligible_for_tier(r, 1) is True
    assert is_so_eligible_for_tier(r, 2) is True


def test_is_so_eligible_for_tier_t34_requires_senior_or_dpm_tag():
    junior = _rec(so_status="SO", job_title="Software Engineer", role_tag="SSOE+SOE")
    assert is_so_eligible_for_tier(junior, 3) is False
    assert is_so_eligible_for_tier(junior, 4) is False

    senior = _rec(so_status="SO", job_title="Senior Software Engineer", role_tag="")
    assert is_so_eligible_for_tier(senior, 3) is True

    dpm_tag = _rec(so_status="SO", job_title="Engineer", role_tag="DPM; WFM")
    assert is_so_eligible_for_tier(dpm_tag, 4) is True


def test_is_so_eligible_for_tier_not_so():
    assert is_so_eligible_for_tier(_rec(so_status="can be SO"), 2) is False


def test_so_eligibility_class_primary_vs_stretch() -> None:
    ok_so = _rec(so_status="SO", job_title="Senior Engineer", role_tag="")
    assert so_eligibility_class(ok_so, 3) == "primary"
    stretched = _rec(so_status="can be SO", job_title="Senior Engineer", role_tag="DPM")
    assert so_eligibility_class(stretched, 3) == "stretch"
    assert so_eligibility_class(stretched, 2) == "stretch"
    junior_cb = _rec(so_status="can be SO", job_title="Engineer", role_tag="SSOE+SOE")
    assert so_eligibility_class(junior_cb, 3) == "ineligible"


def test_skill_rank_score_intersection_plus_half_llm() -> None:
    r = StaffingRecord(
        name="x",
        email="x@t.com",
        job_title="",
        comment="",
        role_tag="",
        so_status="SO",
        skills=("TTS", "Multilingual"),
    )
    assert skill_tag_intersection_size(r, ["TTS", "Evals"]) == 1
    assert skill_rank_score(r, ["TTS", "Evals"], llm_rerank=1.0) == 1.5
    assert skill_rank_score(r, ["TTS", "Evals"], llm_rerank=0.0) == 1.0


def test_skill_match():
    r = StaffingRecord(
        name="x",
        email="x@t.com",
        job_title="",
        comment="",
        role_tag="",
        so_status="SO",
        skills=("TTS", "Multilingual"),
    )
    s = skill_match_score(r, ["TTS", "Evals"], "client wants TTS")
    assert s >= 4
