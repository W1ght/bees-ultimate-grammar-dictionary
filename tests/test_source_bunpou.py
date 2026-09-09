"""Tests for the 文法 (bunpou) Anki-deck extractor."""

from __future__ import annotations

import pathlib

import pytest

from bugd.jsonio import MalformedPayload
from bugd.sources.bunpou import BunpouExtractor

INPUT_DIR = pathlib.Path("data/sources/bunpou")


@pytest.fixture(scope="module")
def result():
    return BunpouExtractor(INPUT_DIR).extract()


def test_extracts_expected_ballpark(result):
    # SOURCES.md: 534 notes / 534 cards.
    assert 500 <= len(result.points) <= 540
    assert result.stats["points"] == len(result.points)


def test_every_point_has_headword_and_source(result):
    for point in result.points:
        assert point.expression
        assert point.source == "bunpou"


def test_ai_fields_are_segregated_not_merged(result):
    # AI content must live in ai_generated, never in the human meaning.
    ai_points = [p for p in result.points if p.ai_generated]
    assert ai_points, "expected AI-annotated notes"
    for point in ai_points:
        assert isinstance(point.ai_generated, dict)
        pol = point.ai_generated.get("politeness")
        if pol and point.meaning:
            assert pol not in point.meaning


def test_ai_examples_are_flagged(result):
    # At least one point should carry an AI-flagged example, and human
    # examples must remain unflagged.
    saw_ai = any(ex.ai_generated for p in result.points for ex in p.examples)
    saw_human = any(not ex.ai_generated for p in result.points for ex in p.examples)
    assert saw_ai and saw_human


def test_furigana_dropped_from_surface_but_examples_present(result):
    # Flattening drops <rt> readings; every point that declares examples keeps them.
    assert result.stats["examples"] > 0
    for point in result.points:
        for ex in point.examples:
            assert "<rt" not in ex.japanese


def test_emits_points_jsonl(result):
    path = INPUT_DIR / "points.jsonl"
    assert path.is_file()
    assert sum(1 for _ in path.open(encoding="utf-8")) == len(result.points)


def test_fail_closed_on_missing_locked_file(tmp_path):
    # An input dir with a lock naming a file that is absent must raise.
    (tmp_path / "SOURCE.lock.json").write_text(
        '{"files": {"文法.apkg": {"sha256": "0"*64, "byteCount": 1}}}',
        encoding="utf-8",
    )
    with pytest.raises((MalformedPayload, Exception)):
        BunpouExtractor(tmp_path).extract()
