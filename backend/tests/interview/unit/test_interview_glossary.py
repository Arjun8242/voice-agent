"""Mis-heard tech terms (v2 design, W4): code puts glossary terms back before any LLM sees the answer,
and never turns an ordinary word into a term."""

from __future__ import annotations

from backend.interview.glossary import normalize_terms

GLOSSARY = ["PostgreSQL", "TypeScript", "Node.js", "React", "FastAPI", "Go"]


def test_split_or_mis_heard_terms_are_put_back_and_reported():
    text, corrections = normalize_terms("We used post gress with fast api, in type script.", GLOSSARY)
    assert text == "We used PostgreSQL with FastAPI, in TypeScript."  # punctuation kept, "in" not swallowed
    assert corrections == {"post gress": "PostgreSQL", "fast api": "FastAPI", "type script": "TypeScript"}


def test_ordinary_words_are_never_turned_into_terms():
    text = "The three nodes go down and it reacts slowly."  # near "Node.js", "Go" and "React"
    assert normalize_terms(text, GLOSSARY) == (text, {})


def test_a_casing_fix_is_not_reported_as_a_correction():
    assert normalize_terms("I wrote it in react.", GLOSSARY) == ("I wrote it in React.", {})


def test_without_a_glossary_the_text_is_untouched():
    assert normalize_terms("post  gress", []) == ("post  gress", {})
