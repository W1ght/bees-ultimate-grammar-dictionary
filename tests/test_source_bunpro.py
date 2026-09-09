"""Bunpro extractor — real invariants over the locked Anki export.

These run against the actual `.apkg` on disk (the reproducible, digest-locked
input the extractor consumes), so they assert the shape of the real corpus, not
a fixture's. The fail-closed and HTML-flattening cases are pure and need no data
file.
"""

from __future__ import annotations

import pathlib

import pytest

from bugd.jsonio import dump_json
from bugd.model import Example
from bugd.sources.base import SOURCE_LOCK_NAME, SourceLockError
from bugd.sources.bunpro import (
    APKG_NAME,
    NOTETYPE,
    BunproExtractor,
    _examples,
    _flatten,
)
from bugd.sources.registry import get_extractor

REPO = pathlib.Path(__file__).resolve().parents[1]
BUNPRO_DIR = REPO / "data" / "sources" / "bunpro"
APKG_PATH = BUNPRO_DIR / APKG_NAME

#: The export ships 964 grammar notes. Assert a tight ballpark rather than an
#: exact count so a benign upstream re-export does not break the suite, but a
#: gross parsing regression (dropping a level, halving the corpus) does.
EXPECTED_POINTS = 964
POINT_FLOOR = 900
POINT_CEILING = 1000

pytestmark = pytest.mark.skipif(
    not APKG_PATH.is_file(),
    reason=f"locked Bunpro export not present: {APKG_PATH}",
)


@pytest.fixture(scope="module")
def result():
    return BunproExtractor(BUNPRO_DIR).extract()


def test_registered_under_its_source_name():
    assert get_extractor("bunpro") is BunproExtractor


def test_point_count_is_in_the_expected_ballpark(result):
    assert result.source == "bunpro"
    assert POINT_FLOOR <= len(result.points) <= POINT_CEILING
    # The real export today is exactly this many; a drift is worth noticing.
    assert len(result.points) == EXPECTED_POINTS
    assert result.stats["notetype"] == NOTETYPE
    # The consumed manifest records the locked digest of the apkg it read.
    assert APKG_NAME in result.consumed
    assert len(result.consumed[APKG_NAME]) == 64


def test_every_point_has_a_headword_and_is_well_formed(result):
    for point in result.points:
        assert point.source == "bunpro"
        assert point.source_id.strip()
        assert point.expression.strip()
        # No HTML tags leaked into the flattened headword.
        assert "<" not in point.expression
    # source_id is the stable per-note Bunpro ID: unique across the corpus.
    ids = [point.source_id for point in result.points]
    assert len(set(ids)) == len(ids)


def test_readings_and_meanings_are_populated_where_the_source_has_them(result):
    # Bunpro glosses every point, so meaning is near-universal; assert it is
    # present for the overwhelming majority rather than every single record.
    with_meaning = sum(1 for point in result.points if point.meaning)
    assert with_meaning >= int(0.95 * len(result.points))
    # Structure is authored for every point.
    assert all(point.structure for point in result.points)
    # Japanese-side prose is carried apart from the English fields.
    assert any(point.nuance_ja for point in result.points)
    assert any(point.explanation_ja for point in result.points)


def test_jlpt_is_read_not_guessed(result):
    levels = {point.jlpt for point in result.points if point.jlpt}
    assert levels <= {"N1", "N2", "N3", "N4", "N5"}
    # The bulk of the deck is levelled; only Non-JLPT / 関西弁 points are None.
    with_jlpt = sum(1 for point in result.points if point.jlpt)
    assert with_jlpt >= int(0.9 * len(result.points))
    # Off-scale Bunpro levels are preserved verbatim in provenance rather than
    # coerced onto the JLPT scale.
    off_scale = [
        point
        for point in result.points
        if point.provenance.get("bunproLevel") in {"Non-JLPT", "関西弁"}
    ]
    assert off_scale
    assert all(point.jlpt is None for point in off_scale)


def test_examples_are_attached_with_translation_highlight_and_html(result):
    assert result.stats["withExamples"] >= int(0.95 * len(result.points))
    # Thousands of example sentences across the corpus.
    total = sum(len(point.examples) for point in result.points)
    assert total > 10_000
    assert result.stats["examples"] == total

    saw_english = saw_highlight = saw_html = False
    for point in result.points:
        for example in point.examples:
            assert example.japanese.strip()
            assert "<" not in example.japanese  # flattened surface text
            if example.english:
                saw_english = True
            if example.highlight:
                saw_highlight = True
            if example.japanese_html is not None:
                saw_html = True
                # Invariant: the annotated form flattens back to the surface.
                assert _flatten(example.japanese_html) == example.japanese
    assert saw_english and saw_highlight and saw_html


def test_licence_tier_and_attribution_travel_on_every_record(result):
    assert result.stats["licenseTier"] == "C"
    assert result.stats["redistributable"] is False
    for point in result.points:
        provenance = point.provenance
        assert provenance["sourceLabel"] == "Bunpro Grammar Reference"
        assert provenance["licenseTier"] == "C"
        assert provenance["redistributable"] is False


def test_fails_closed_when_a_locked_file_is_missing(tmp_path):
    """A lock that names the apkg without the bytes present must fail closed."""
    directory = tmp_path / "bunpro"
    directory.mkdir()
    lock = {
        "source": "bunpro",
        "files": {
            APKG_NAME: {"sha256": "0" * 64, "byteCount": 1},
        },
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    with pytest.raises(SourceLockError, match="missing"):
        BunproExtractor(directory).extract()


def test_fails_closed_when_the_lock_does_not_list_the_apkg(tmp_path):
    directory = tmp_path / "bunpro"
    directory.mkdir()
    lock = {
        "source": "bunpro",
        "files": {"something-else.txt": {"sha256": "0" * 64, "byteCount": 1}},
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    (directory / "something-else.txt").write_bytes(b"x")
    with pytest.raises(Exception, match="missing|not listed"):
        BunproExtractor(directory).extract()


def test_fails_closed_on_a_digest_mismatch(tmp_path):
    """Wrong bytes under a correct name are refused, not parsed."""
    directory = tmp_path / "bunpro"
    directory.mkdir()
    payload = b"not really an apkg"
    lock = {
        "source": "bunpro",
        "files": {
            APKG_NAME: {"sha256": "0" * 64, "byteCount": len(payload)},
        },
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    (directory / APKG_NAME).write_bytes(payload)
    with pytest.raises(SourceLockError, match="digest mismatch"):
        BunproExtractor(directory).extract()


# --------------------------------------------------------------------------
# Pure helpers — no data file required.
# --------------------------------------------------------------------------


def test_flatten_drops_furigana_readings_and_tags():
    assert _flatten("<ruby>私<rt>わたし</rt></ruby>だ。") == "私だ。"
    assert _flatten("Noun + <strong>だ</strong>") == "Noun + だ"
    assert _flatten("<br><br>Noun") == "Noun"
    assert _flatten("") is None
    assert _flatten(None) is None
    assert _flatten("   ") is None


def test_examples_pair_japanese_english_highlight_and_preserve_html():
    field = (
        '<div class="example-item">'
        '<div class="example-text">'
        '<div class="japanese"><ruby>私<rt>わたし</rt></ruby>'
        '<span class="highlight">だ</span>。</div>'
        '<div class="english">It <strong>is</strong> me.</div>'
        "</div></div>"
    )
    examples = _examples(field)
    assert len(examples) == 1
    example = examples[0]
    assert isinstance(example, Example)
    assert example.japanese == "私だ。"
    assert example.english == "It is me."
    assert example.highlight == ("だ",)
    assert example.japanese_html == (
        '<ruby>私<rt>わたし</rt></ruby><span class="highlight">だ</span>。'
    )
    assert _flatten(example.japanese_html) == example.japanese


def test_examples_dedupe_repeated_sentences_and_skip_empty_items():
    field = (
        '<div class="example-item"><div class="japanese">同じ。</div>'
        '<div class="english">Same.</div></div>'
        '<div class="example-item"><div class="japanese">同じ。</div>'
        '<div class="english">Same again.</div></div>'
        '<div class="example-item"><div class="notjapanese">x</div></div>'
    )
    examples = _examples(field)
    assert [e.japanese for e in examples] == ["同じ。"]


def test_empty_example_field_yields_no_examples():
    assert _examples("") == ()
    assert _examples("no example items here") == ()
