"""Tests for the S6 runner's logic and for the smoke labels themselves.
No embedding model is needed; the real-KB test is skipped if the folder is absent."""

from pathlib import Path

import pytest

from evals import run_smoke as rs

ROOT = Path(__file__).resolve().parents[2]


def chunk(source, section, score, text="body"):
    return {"text": text, "score": score, "metadata": {"source": source, "section": section, "id": "x"}}


Q_DIRECT = {"id": "d", "type": "direct", "query": "q",
            "expect": [{"source": "a.md", "heading": "Why X?", "contains": ["alpha"]}]}
Q_NONE = {"id": "n", "type": "unanswerable", "query": "q"}


def test_title_match_uses_heading_boundary():
    assert rs.title_matches("Beacon > Overview", "Overview")
    assert rs.title_matches("Valyrian > Language Features > Arrays", "Language Features > Arrays")
    assert not rs.title_matches("Valyrian > Language Features > Arrays", "rays")
    assert not rs.title_matches("Beacon > Overview extra", "Overview")


def test_direct_passes_when_right_chunk_is_above_threshold():
    chunks = [chunk("b.md", "T > Other", 0.9), chunk("a.md", "T > Why X?", 0.7, "Alpha text")]
    r = rs.evaluate(Q_DIRECT, chunks, 0.5)
    assert r["passed"] and r["rank"] == 2


def test_direct_fails_when_right_chunk_below_threshold():
    r = rs.evaluate(Q_DIRECT, [chunk("a.md", "T > Why X?", 0.4, "alpha")], 0.5)
    assert r["passed"] is False and "scored 0.400" in r["note"]


def test_contains_is_enforced():
    r = rs.evaluate(Q_DIRECT, [chunk("a.md", "T > Why X?", 0.9, "no keyword")], 0.5)
    assert r["passed"] is False and "not in top-k" in r["note"]


def test_wrong_source_does_not_match():
    r = rs.evaluate(Q_DIRECT, [chunk("other.md", "T > Why X?", 0.9, "alpha")], 0.5)
    assert r["passed"] is False


def test_unanswerable_passes_only_if_nothing_clears_threshold():
    assert rs.evaluate(Q_NONE, [chunk("a.md", "T > A", 0.45)], 0.5)["passed"] is True
    assert rs.evaluate(Q_NONE, [chunk("a.md", "T > A", 0.55)], 0.5)["passed"] is False
    assert rs.evaluate(Q_NONE, [], 0.5)["passed"] is True


def test_exploratory_is_never_counted():
    q = {"id": "e", "type": "exploratory", "query": "q"}
    assert rs.evaluate(q, [chunk("a.md", "T > A", 0.9)], 0.5)["passed"] is None


def test_sweep_finds_separating_window():
    results = {"d": [chunk("a.md", "T > Why X?", 0.70, "alpha")], "n": [chunk("a.md", "T > A", 0.50)]}
    s = rs.sweep([Q_DIRECT, Q_NONE], results)
    assert s["window"] == (0.50, 0.70)
    both = [r["t"] for r in s["rows"] if r["ans"] == r["ans_n"] and r["una"] == r["una_n"]]
    assert both == [0.55, 0.60, 0.65, 0.70] or both == [0.55, 0.6, 0.65, 0.7]


def test_sweep_reports_overlap_and_misses():
    results = {"d": [chunk("a.md", "T > Why X?", 0.45, "alpha")], "n": [chunk("a.md", "T > A", 0.60)]}
    assert rs.sweep([Q_DIRECT, Q_NONE], results)["window"] is None
    results = {"d": [chunk("zzz.md", "T > Nope", 0.9)], "n": []}
    assert rs.sweep([Q_DIRECT, Q_NONE], results)["misses"] == ["d"]


def test_check_questions_catches_bad_input():
    bad = [{"id": "a", "type": "direct", "query": "q"},
           {"id": "a", "type": "unanswerable", "query": "q", "expect": [{"source": "x", "heading": "y"}]},
           {"id": "c", "type": "wrong", "query": "q"}]
    errs = rs.check_questions(bad)
    assert any("non-empty 'expect'" in e for e in errs)
    assert any("duplicate id" in e for e in errs)
    assert any("must not have 'expect'" in e for e in errs)
    assert any("type must be" in e for e in errs)


def test_smoke_file_is_well_formed():
    qs = rs.load_questions(rs.DEFAULT_FILE)
    assert rs.check_questions(qs) == []
    counted = [q for q in qs if q["type"] != "exploratory"]
    assert len(counted) >= 10
    kinds = {q["type"] for q in qs}
    assert {"direct", "followup", "boundary", "unanswerable", "exploratory"} <= kinds


@pytest.mark.skipif(not (ROOT / "knowledge_base").exists(), reason="no knowledge_base folder")
def test_every_label_matches_a_real_chunk():
    from backend.kb.ingest import build_chunks

    records = [{"source": c.source, "title": c.title, "content": c.content} for c in build_chunks(ROOT / "knowledge_base")]
    assert rs.check_labels(rs.load_questions(rs.DEFAULT_FILE), records) == []
