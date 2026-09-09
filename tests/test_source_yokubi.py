"""Yokubi extractor against the real acquired corpus.

These tests run against `data/sources/yokubi/` — the mdBook markdown already
acquired into the repo — never a synthetic fixture, so they assert the actual
invariants the extractor's contract promises.
"""

from __future__ import annotations

import pathlib

import pytest

from bugd.jsonio import load_json
from bugd.model import GrammarPoint
from bugd.sources.base import ExtractResult, SourceLockError
from bugd.sources.registry import get_extractor
from bugd.sources.yokubi import (
    ATTRIBUTION,
    LICENSE_TIER,
    REDISTRIBUTABLE,
    YokubiExtractor,
    is_japanese,
    lesson_examples,
    title_headwords,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "data" / "sources" / "yokubi"


@pytest.fixture(scope="module")
def result() -> ExtractResult:
    return YokubiExtractor(CORPUS).extract()


# --- registration ---------------------------------------------------------


def test_registered_under_yokubi():
    assert get_extractor("yokubi") is YokubiExtractor
    assert YokubiExtractor.name == "yokubi"
    assert YokubiExtractor.ai_generated_source is False


# --- unit rules on the headword derivation --------------------------------


def test_headwords_derive_only_from_title_japanese_tokens():
    # The English words in the title never become headwords.
    assert title_headwords("Lesson 1: State of being with だ and です".split(": ", 1)[1]) == [
        "だ",
        "です",
    ]
    assert title_headwords("State of being with だ and です") == ["だ", "です"]


def test_title_with_no_japanese_yields_no_headword():
    assert title_headwords("The anatomy of Japanese sentences") == []
    assert title_headwords("Nouns, pronouns") == []


def test_is_japanese_detects_scripts():
    assert is_japanese("だ") and is_japanese("自分") and is_japanese("ネコ")
    assert not is_japanese("anatomy") and not is_japanese("N5")


# --- corpus-wide invariants -----------------------------------------------


def test_extracts_all_64_lessons(result):
    assert result.source == "yokubi"
    assert result.stats["lessons"] == 64
    # 50 lessons declare a Japanese headword; 14 are title-less and skipped.
    assert result.stats["skippedCount"] == 14
    assert result.stats["lessons"] == result.stats["skippedCount"] + 50


def test_every_point_is_valid_and_self_attributed(result):
    assert result.points, "expected at least one grammar point"
    for point in result.points:
        assert isinstance(point, GrammarPoint)
        assert point.source == "yokubi"
        assert is_japanese(point.expression)


def test_headwords_come_only_from_their_lesson_title(result):
    # Reconstruct the expected headword set straight from lesson H1s and assert
    # the extractor invented nothing beyond the title-declared tokens.
    for point in result.points:
        title = point.provenance["lessonTitle"]
        assert point.expression in title_headwords(title)


def test_skipped_lessons_are_recorded_with_a_reason(result):
    skipped = result.stats["skippedLessons"]
    nums = {entry["lesson"] for entry in skipped}
    # Lesson 0 ("The anatomy of Japanese sentences") declares no Japanese token.
    assert 0 in nums
    assert 2 in nums  # "Nouns, pronouns"
    for entry in skipped:
        assert entry["reason"]
        assert title_headwords(entry["title"]) == []
    # A skipped lesson never leaks a point.
    skipped_lessons = {entry["lesson"] for entry in skipped}
    for point in result.points:
        assert point.provenance["lesson"] not in skipped_lessons


def test_da_and_desu_are_lesson1_headwords(result):
    lesson1 = [p for p in result.points if p.provenance["lesson"] == 1]
    assert {p.expression for p in lesson1} == {"だ", "です"}


# --- example attachment requires substring containment --------------------


def test_attached_examples_all_contain_their_headword(result):
    saw_attachment = False
    for point in result.points:
        for example in point.examples:
            saw_attachment = True
            assert point.expression in example.japanese
    assert saw_attachment, "expected at least one attached example"


def test_da_attaches_only_containing_examples(result):
    (da,) = [
        p for p in result.points if p.provenance["lesson"] == 1 and p.expression == "だ"
    ]
    japanese = {ex.japanese for ex in da.examples}
    assert "ペンだ。" in japanese  # contains だ
    assert "ネコです。" not in japanese  # だ not a substring -> not attached


def test_lesson_examples_reads_pre_blocks():
    body = (CORPUS / "src" / "Section1" / "Part1" / "Lesson1.md").read_text("utf-8")
    examples = lesson_examples(body)
    japanese = {ex.japanese for ex in examples}
    assert "ペンだ。" in japanese
    # The English gloss line becomes the following example's translation.
    pen = next(ex for ex in examples if ex.japanese == "ペンだ。")
    assert pen.english == "It's a pen."


# --- attribution / licence ------------------------------------------------


def test_attribution_present_on_every_point(result):
    assert ATTRIBUTION == "Yokubi — The Common Grammar Guide (https://yoku.bi), CC BY 4.0"
    for point in result.points:
        assert point.provenance["attribution"] == ATTRIBUTION
        assert point.provenance["licenseTier"] == LICENSE_TIER == "A"
        assert point.provenance["redistributable"] is REDISTRIBUTABLE is True
    assert result.stats["attribution"] == ATTRIBUTION
    assert result.stats["licenseTier"] == "A"
    assert result.stats["redistributable"] is True


# --- fails closed on a missing locked lesson ------------------------------


def test_missing_locked_lesson_fails_closed(tmp_path):
    """A SUMMARY lesson absent from the lock raises rather than yielding fewer."""
    lock = load_json((CORPUS / "SOURCE.lock.json").read_text("utf-8"))
    # Drop one real lesson from the lock so read_locked_bytes must refuse it.
    victim = "src/Section1/Part1/Lesson1.md"
    assert victim in lock["files"]
    del lock["files"][victim]

    staged = tmp_path / "yokubi"
    (staged / "src").mkdir(parents=True)
    import json

    (staged / "SOURCE.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    # Only stage SUMMARY.md (which still lists Lesson 1) — the lesson body is
    # both unlocked and absent, so the extractor must fail closed.
    summary = (CORPUS / "src" / "SUMMARY.md").read_text("utf-8")
    (staged / "src" / "SUMMARY.md").write_text(summary, encoding="utf-8")

    with pytest.raises(SourceLockError):
        YokubiExtractor(staged).extract()


def test_consumed_lists_summary_and_lessons(result):
    assert result.consumed["src/SUMMARY.md"] == "index"
    lesson_keys = [k for k, v in result.consumed.items() if v == "lesson"]
    assert len(lesson_keys) == 64
    assert "src/Section1/Part1/Lesson1.md" in lesson_keys
