"""Bunpro extractor — real invariants over the locked Anki export.

These run against the actual `.apkg` on disk (the reproducible, digest-locked
input the extractor consumes), so they assert the shape of the real corpus, not
a fixture's. The fail-closed and HTML-flattening cases are pure and need no data
file.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.jsonio import dump_json
from bugd.model import Example
from bugd.normalize import sentence_key, split_alternatives
from bugd.pipeline import point_from_json
from bugd.sources.base import JSONL_NAME, SOURCE_LOCK_NAME, SourceLockError
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


def test_the_source_label_travels_on_every_record(result):
    """Every record names the source that made it -- that is the card's badge."""
    for point in result.points:
        assert point.provenance["sourceLabel"] == "Bunpro Grammar Reference"


def test_normalized_jsonl_lands_beside_the_locked_bytes(result):
    """The card's deliverable: one normalized record per line in the source dir."""
    path = BUNPRO_DIR / JSONL_NAME
    assert result.stats["jsonl"] == JSONL_NAME
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(result.points)
    records = [json.loads(line) for line in lines]
    # Every line round-trips back into the same record the extractor emitted, so
    # the artifact is the corpus rather than a lossy summary of it.
    assert [point_from_json(record) for record in records] == list(result.points)
    assert all(record["source"] == "bunpro" for record in records)


def test_extract_writes_the_jsonl_rather_than_relying_on_a_stale_one(tmp_path):
    """The write must be the extractor's own side effect.

    Asserting `path.is_file()` in the shared source directory passes even if the
    extractor stopped writing, because a previous run left the file there. Point
    the extractor at a fresh directory holding only the locked inputs, so the
    JSONL can only exist if THIS run produced it.
    """
    directory = tmp_path / "bunpro"
    directory.mkdir()
    (directory / SOURCE_LOCK_NAME).write_bytes((BUNPRO_DIR / SOURCE_LOCK_NAME).read_bytes())
    (directory / APKG_NAME).symlink_to(APKG_PATH.resolve())

    path = directory / JSONL_NAME
    assert not path.exists()
    result = BunproExtractor(directory).extract()
    assert path.is_file(), "extract() did not write its JSONL deliverable"
    assert len(path.read_text(encoding="utf-8").splitlines()) == len(result.points)


def test_jsonl_is_deterministic_over_identical_locked_bytes():
    """Two runs over the same bytes produce byte-identical JSONL."""
    path = BUNPRO_DIR / JSONL_NAME
    BunproExtractor(BUNPRO_DIR).extract()
    first = path.read_bytes()
    BunproExtractor(BUNPRO_DIR).extract()
    assert path.read_bytes() == first


def test_the_audited_furigana_fixups_are_actually_applied(result):
    """UGD-11a's table must reach the records, not just exist in the tree.

    The 13 occurrences below were verified present in the raw deck HTML, so a
    corrected corpus must contain none of them and the extractor must report
    having changed the fields that carried them.
    """
    assert result.stats["furiganaFixupsApplied"] > 0
    wrong_pairs = {
        ("思", "あも"),
        ("私", "またし"),
        ("学", "なな"),
        ("対", "つか"),
        ("使", "かた"),
    }
    # The wrong reading must not survive anywhere the annotated form is kept.
    for point in result.points:
        for example in point.examples:
            if example.japanese_html is None:
                continue
            for base, wrong in wrong_pairs:
                assert f"<ruby>{base}<rt>{wrong}</rt></ruby>" not in example.japanese_html


def test_headword_alternates_become_lookup_variants(result):
    """`けど・だけど` must resolve under both spellings, not only the first."""
    with_variants = [point for point in result.points if point.variants]
    assert with_variants
    for point in with_variants:
        # A variant is a genuine alternate of the same headword, never a repeat.
        assert point.expression not in point.variants
        assert len(set(point.variants)) == len(point.variants)
        assert set(point.variants) <= set(split_alternatives(point.expression))
    assert result.stats["pointsWithVariants"] == len(with_variants)


def test_dedup_relevant_keys_are_reported_and_unique_where_claimed(result):
    stats = result.stats
    # source_id: Bunpro's own per-note ID, unique across the corpus.
    assert stats["distinctSourceIds"] == len(result.points)
    # Alternates expand the corpus's lookup surface beyond one key per point.
    assert stats["distinctLookupKeys"] > len(result.points)
    # Example identity is reported on the same normalized key the merge stage
    # dedupes on, so a reviewer can see the duplicate budget before merging.
    keys = {
        sentence_key(example.japanese)
        for point in result.points
        for example in point.examples
    }
    assert stats["distinctSentenceKeys"] == len(keys)
    assert stats["distinctSentenceKeys"] <= stats["examples"]


def test_off_scale_levels_survive_as_notes_not_as_a_guessed_badge(result):
    off_scale = [
        point
        for point in result.points
        if point.provenance.get("bunproLevel") in {"Non-JLPT", "関西弁"}
    ]
    assert off_scale
    for point in off_scale:
        assert point.jlpt is None
        # The marker itself is preserved rather than discarded.
        assert point.notes in {"Non-JLPT", "関西弁"}


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


def test_flatten_drops_rp_ruby_fallback_parens():
    """`<rp>` must not survive into the plain-text surface string.

    Those are the parentheses a browser paints ONLY when it cannot render ruby,
    so a renderer that paints `<rt>` never paints them. Keeping them left an empty
    `（）` in the surface text -- and the surface string is exactly what example
    dedup (`sentence_key`) and highlight substring matching compare on.
    """
    ruby = "<ruby>親切<rp>（</rp><rt>しんせつ</rt><rp>）</rp></ruby>だ。"
    surface = _flatten(ruby)
    assert surface == "親切だ。"
    assert surface is not None and "（" not in surface and "）" not in surface
    # Latin-parenthesis form too, and rp with attributes.
    assert _flatten("<ruby>読<rp >(</rp><rt>よ</rt><rp>)</rp></ruby>む") == "読む"


def test_examples_strip_rp_from_the_surface_but_keep_it_in_the_annotated_html():
    """The invariant that binds the two forms must hold for rp-bearing ruby."""
    field = (
        '<div class="example-item">'
        '<div class="japanese"><ruby>親切<rp>（</rp><rt>しんせつ</rt><rp>）</rp></ruby>だ。</div>'
        '<div class="english">It is kind.</div></div>'
    )
    (example,) = _examples(field)
    assert example.japanese == "親切だ。"
    annotated = example.japanese_html
    assert annotated is not None and "<rp>" in annotated  # source markup verbatim
    assert _flatten(annotated) == example.japanese


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
