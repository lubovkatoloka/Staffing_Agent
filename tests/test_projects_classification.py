from pathlib import Path

from staffing_agent.projects_classification import (
    _score_row,
    build_similar_projects_markdown,
    load_classification_rows,
)


def test_score_row_prefers_tag_overlap():
    row = {
        "Capability Domain": "TTS, Evals",
        "Notes": "multilingual",
        "Project Name": "X",
        "Client": "C",
    }
    assert _score_row(row, ["TTS", "Evals"], "client wants TTS eval") > 0


def test_build_similar_with_fixture_csv(tmp_path: Path, monkeypatch):
    csv_text = (
        "Project Name,Client,Capability Domain,Notes\n"
        'P1,Acme,"TTS, Evals",test\n'
        'P2,Other,Coding,none\n'
    )
    p = tmp_path / "c.csv"
    p.write_text(csv_text, encoding="utf-8")

    import staffing_agent.projects_classification as pc

    monkeypatch.setattr(pc, "default_csv_path", lambda: p)
    text = build_similar_projects_markdown(["TTS"], "evaluation project", max_similar=3)
    assert "Похожие проекты" in text
    assert "Acme" in text or "P1" in text


def test_load_real_export_if_present():
    rows = load_classification_rows()
    if not rows:
        return
    assert "Project Name" in rows[0] or "project name" in {k.lower() for k in rows[0]}
