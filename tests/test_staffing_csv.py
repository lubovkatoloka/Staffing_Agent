from staffing_agent.staffing_csv import (
    comment_blocks_staffing,
    is_so_or_can_be_so,
    skill_match_score,
)
from staffing_agent.staffing_csv import StaffingRecord


def test_is_so():
    assert is_so_or_can_be_so("SO") is True
    assert is_so_or_can_be_so("can be SO") is True
    assert is_so_or_can_be_so("Executor") is False
    assert is_so_or_can_be_so("") is False


def test_comment_block():
    cfg = {"comment_block_patterns": [r"(?i)do not staff"]}
    assert comment_blocks_staffing("Please do not staff this week", cfg) is True
    assert comment_blocks_staffing("available", cfg) is False


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
