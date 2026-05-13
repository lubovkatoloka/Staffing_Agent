from staffing_agent.decision.capacity import CapacityRow
from staffing_agent.decision.enums import Band
from staffing_agent.format_utils import (
    band_label_for_slack,
    project_status_risk_rank,
    risk_breakdown_summary,
    truncate_at_word_boundary,
    truncate_overcap_projects,
    project_status_word,
)


def test_truncate_at_word_boundary_no_mid_word_cut():
    s = "MS Copilot Orchestration Omega Studio Pilot Phase"
    out = truncate_at_word_boundary(s, 40)
    assert len(out) <= 40
    assert "Omeg…" not in out
    assert out.endswith("…")
    assert "Copilot" in out


def test_project_status_word_omits_on_track():
    assert project_status_word("ON_TRACK") is None
    assert project_status_word("BEHIND") == "BEHIND"


def test_band_over_cap_label():
    assert band_label_for_slack(Band.AT_CAP) == "OVER_CAP"
    assert band_label_for_slack(Band.FREE) == "FREE"


def test_project_status_risk_rank_orders_behind_first():
    assert project_status_risk_rank("BEHIND") < project_status_risk_rank("AT_RISK")
    assert project_status_risk_rank("AT_RISK") < project_status_risk_rank("ON_TRACK")


def test_truncate_overcap_projects_risk_order():
    rows = [
        CapacityRow("1", "A", "Tier 3", "building", "ON_TRACK"),
        CapacityRow("2", "B", "Tier 3", "building", "BEHIND"),
        CapacityRow("3", "C", "Tier 3", "building", "AT_RISK"),
        CapacityRow("4", "D", "Tier 3", "building", "ON_TRACK"),
    ]
    frag, more = truncate_overcap_projects(rows, top_n=3)
    assert more == 1
    assert "B" in frag and frag.index("B") < frag.index("C")


def test_risk_breakdown_summary_skips_on_track():
    rows = [
        CapacityRow("1", "A", "Tier 3", "building", "BEHIND"),
        CapacityRow("2", "B", "Tier 3", "building", "ON_TRACK"),
        CapacityRow("3", "C", "Tier 3", "building", "AT_RISK"),
    ]
    assert "BEHIND 1" in risk_breakdown_summary(rows)
    assert "AT_RISK 1" in risk_breakdown_summary(rows)
