from staffing_agent.node3_row_utils import project_role_norm
from staffing_agent.node3_tier_preview import occupation_preview_caption_suffix, occupation_preview_roles


def test_preview_roles_tier2_includes_wfm_qm():
    r = occupation_preview_roles(2)
    assert r is not None
    assert r == frozenset({"soe", "dpm", "wfm", "qm"})


def test_preview_roles_tier1():
    r = occupation_preview_roles(1)
    assert r == frozenset({"dpm", "wfm", "qm"})


def test_preview_roles_none_tier():
    assert occupation_preview_roles(None) is None


def test_caption_tier2():
    s = occupation_preview_caption_suffix(2)
    assert "Tier 2" in s
    assert "dpm" in s and "soe" in s
    assert "show 15" in s


def test_caption_max_shown():
    s = occupation_preview_caption_suffix(2, max_shown=5)
    assert "show 5" in s


def test_caption_no_tier():
    s = occupation_preview_caption_suffix(None)
    assert "show 15" in s
    assert "Tier" not in s


def test_filter_rows_matches_tier2_logic():
    rows = [
        {"user_name": "W", "project_role": "wfm", "occupation": 0.1},
        {"user_name": "S", "project_role": "soe", "occupation": 0.2},
        {"user_name": "D", "project_role": "dpm", "occupation": 0.15},
        {"user_name": "Q", "project_role": "qm", "occupation": 0.12},
    ]
    rf = occupation_preview_roles(2)
    preview = [r for r in rows if project_role_norm(r) in rf]
    names = {r["user_name"] for r in preview}
    assert names == {"W", "S", "D", "Q"}
