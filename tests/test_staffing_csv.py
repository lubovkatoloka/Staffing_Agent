from staffing_agent.staffing_csv import (
    StaffingRecord,
    is_so_or_can_be_so,
    skill_match_score,
)


def test_is_so():
    assert is_so_or_can_be_so("SO") is True
    assert is_so_or_can_be_so("can be SO") is True
    assert is_so_or_can_be_so("Executor") is False
    assert is_so_or_can_be_so("") is False


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
