"""Slack slim-response acceptance checks (CR-4 skeleton)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from staffing_agent.config_loader import load_decision_config
from staffing_agent.decision import CapacityRow, assess
from staffing_agent.decision.team_template import team_template_for
from staffing_agent.models.request_spec import RequestSpec
from staffing_agent.node4_recommendation import build_project_recommendation_markdown
from staffing_agent.paste_run import build_reply_from_paste
from staffing_agent.staffing_csv import StaffingRecord


def _proj(
    pid: str,
    pname: str,
    *,
    tier: str = "Tier 2",
    stage: str = "building",
    status: str = "ON_TRACK",
) -> CapacityRow:
    return CapacityRow(project_id=pid, project_name=pname, tier=tier, stage=stage, status=status)


def _person(email: str, name: str, role: str, cfg: dict, tier_ctx: int, *projects: CapacityRow) -> dict:
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


def _so(email: str) -> StaffingRecord:
    return StaffingRecord(
        name=email.split("@")[0],
        email=email,
        job_title="",
        comment="",
        role_tag="",
        so_status="SO",
        skills=(),
    )


@pytest.fixture
def tier2_stub_rows():
    cfg = load_decision_config()
    staffing = {
        "f@test.com": _so("f@test.com"),
        "s@test.com": _so("s@test.com"),
        "w1@test.com": _so("w1@test.com"),
        "w2@test.com": _so("w2@test.com"),
    }
    rows = [
        _person("f@test.com", "FirstPick", "dpm", cfg, 2, _proj("p1", "Alpha")),
        _person("s@test.com", "SecondFree", "soe", cfg, 2, _proj("p2", "Beta"), _proj("p3", "Gamma")),
        _person("w1@test.com", "WfmOne", "wfm", cfg, 2, _proj("w1", "Omega")),
        _person("w2@test.com", "WfmTwo", "wfm", cfg, 2, _proj("w2", "Zeta")),
    ]
    return cfg, staffing, rows


def test_canonical_paste_mock_within_budget(monkeypatch: pytest.MonkeyPatch, tier2_stub_rows) -> None:
    cfg, staffing, rows = tier2_stub_rows

    def _fake_node3(**kw: object) -> str:
        assert kw["tier"] == 2
        return build_project_recommendation_markdown(
            rows,
            tier=2,
            decision_cfg=cfg,
            staffing_by_email=staffing,
            detail="minimal",
        )

    monkeypatch.setenv("STAFFING_AGENT_MOCK_LLM", "1")
    monkeypatch.setenv("STAFFING_AGENT_REPLY_STYLE", "minimal")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("staffing_agent.paste_run.node3_slack_markdown", _fake_node3)

    sample_path = Path(__file__).resolve().parents[1] / "examples" / "sample_thread.txt"
    reply, src = build_reply_from_paste(sample_path.read_text(encoding="utf-8"))
    assert src == "mock"

    assert len(reply) <= 1500
    lines = reply.count("\n") + (1 if reply.strip() else 0)
    assert lines <= 20

    lower = reply.lower()
    for bad in (
        "situation:",
        "complication:",
        "answer:",
        "node 2 — candidate pool",
        "currently on projects",
        "skills match ≈",
    ):
        assert bad not in lower

    assert "**" not in reply
    for medal in ("🥇", "🥈", "🥉"):
        assert medal not in reply

    assert " · SO" not in reply
    assert " · can-be-SO" not in reply
    assert " · can be SO" not in reply
    assert "*qm recommendations*" not in lower
    assert "*qc recommendations*" not in lower

    header_line = reply.split("\n", 1)[0].strip()
    tier_re = re.compile(r"^\*Tier [1-4] · [SML]: .+\* — .{1,80}$")
    assert tier_re.match(header_line), header_line

    n_sections = len(re.findall(r"\*[^\n]* Recommendations\*", reply))
    assert n_sections == len(team_template_for(2, sese_path=False))


def test_tier_line_fallback_without_judge() -> None:
    spec = RequestSpec(tier=2, complexity_class="S", judge="")
    header = spec.tier_slack_header_mrkdwn()
    assert header == "*Tier 2 · S: SoE/DPM + WFM*"
    assert " — " not in header
