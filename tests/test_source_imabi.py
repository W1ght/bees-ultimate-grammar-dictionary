"""IMABI extractor tests.

Exercises the real corpus under `data/sources/imabi/` (present in the checkout)
for the happy path, and a tmp_path copy for the fail-closed contract so the
committed source directory is never mutated.
"""

from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from bugd.jsonio import MalformedPayload
from bugd.sources.imabi import (
    ATTRIBUTION,
    COVERAGE_NAME,
    JSONL_NAME,
    META_PAGE_IDS,
    ImabiExtractor,
    render_coverage,
    skip_reason,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SOURCE_DIR = _REPO / "data" / "sources" / "imabi"


@pytest.fixture(scope="module")
def result():
    return ImabiExtractor(_SOURCE_DIR).extract()


def test_source_directory_is_present():
    assert (_SOURCE_DIR / "SOURCE.lock.json").is_file(), (
        "IMABI corpus must be acquired under data/sources/imabi/"
    )


def test_point_count_is_in_a_sane_ballpark(result):
    # ~497 lessons after excluding a handful of site-meta pages; assert hundreds.
    assert 400 <= len(result.points) <= 501, len(result.points)


def test_points_have_non_empty_headwords(result):
    assert result.points, "expected lesson points"
    for point in result.points:
        assert point.source == "imabi"
        assert point.expression.strip(), "every lesson must have a headword"
        assert point.source_id.strip()


def test_example_attachment_works(result):
    total = sum(len(point.examples) for point in result.points)
    # The prototype paired ~18k numbered examples across the corpus.
    assert total > 1000, total
    with_examples = [p for p in result.points if p.examples]
    assert with_examples, "at least some lessons must carry examples"
    # At least one example must have both Japanese and an English translation.
    paired = [
        ex
        for point in with_examples
        for ex in point.examples
        if ex.english and ex.japanese
    ]
    assert paired, "example pairing must attach English translations"


def test_attribution_present(result):
    assert result.stats["attribution"] == ATTRIBUTION
    for point in result.points:
        prov = point.provenance
        assert prov["attribution"] == ATTRIBUTION
        assert prov["sourceLabel"] == "IMABI"


def test_extract_fails_closed_when_a_locked_page_is_removed(tmp_path):
    work = tmp_path / "imabi"
    shutil.copytree(_SOURCE_DIR, work)

    lock = json.loads((work / "SOURCE.lock.json").read_text(encoding="utf-8"))
    page = next(p for p in lock["files"] if p.startswith("pages/"))
    (work / page).unlink()

    with pytest.raises(MalformedPayload):
        ImabiExtractor(work).extract()


# ---------------------------------------------------------------------------
# Every locked page is accounted for, and non-lesson pages are named
# ---------------------------------------------------------------------------
#
# Regression for three site-meta pages that reached the emitted records as the
# headwords "STYLE GUIDE" (a WordPress theme test page), "Imabi's Little crew"
# (the author biography) and "Welcome to IMABI!" (the site landing page). The
# card asks for substantive lesson content, so these are defects, not content.

#: (page id, headword) pairs that are demonstrably not lessons.
NON_LESSON_PAGES = (
    (7, "Contact"),
    (8, "About"),
    (11, "Welcome to IMABI!"),
    (20, "Table of Contents"),
    (33, "STYLE GUIDE"),
    (535, "About"),
    (2207, "Little crew"),
)


def test_locked_pages_equal_imported_plus_skipped(result):
    stats = result.stats
    assert stats["importedLessons"] + stats["skippedPages"] == stats["lockedPages"], stats
    assert stats["importedLessons"] == len(result.points)


def test_every_non_lesson_page_is_skipped_with_a_reason(result):
    skipped_ids = {int(skip["pageId"]) for skip in result.stats["skips"]}
    for page_id, label in NON_LESSON_PAGES:
        assert page_id in skipped_ids, f"page {page_id} ({label}) must be skipped"
    for skip in result.stats["skips"]:
        assert str(skip["reason"]).strip(), f"skip {skip['pageId']} carries no reason"


def test_non_lesson_headwords_are_absent_from_the_records(result):
    headwords = {point.expression for point in result.points}
    source_ids = {point.source_id for point in result.points}
    for page_id, _ in NON_LESSON_PAGES:
        assert str(page_id) not in source_ids, f"page {page_id} was imported as a lesson"
    for bad in ("STYLE GUIDE", "Welcome to IMABI!"):
        assert bad not in headwords, bad
    assert not any("Little crew" in head for head in headwords)


def test_landing_page_is_excluded_by_id_because_its_slug_is_percent_encoded():
    # Its slug is the percent-encoded Japanese title, so no readable slug rule
    # can match it; the exclusion must therefore be keyed on the page id.
    assert 11 in META_PAGE_IDS
    assert skip_reason(11, "%e3%82%88%e3%81%86", "Welcome to IMABI!") is not None
    # A real Japanese-titled lesson with a percent-encoded slug still imports.
    assert skip_reason(9999, "%e3%81%aa%e3%81%8c%e3%82%89", "The Particle ば") is None


def test_a_page_with_no_headword_is_skipped_with_a_reason():
    # No page in the current locked spine has an empty title, so this guard is
    # unreachable through the corpus fixture and is asserted directly -- without
    # it, deleting the guard leaves the whole suite green.
    reason = skip_reason(9999, "some-lesson", "")
    assert reason is not None and reason.strip()
    assert "headword" in reason


def test_substantive_lessons_still_import(result):
    # Classical Japanese is explicitly in scope for this card.
    headwords = [point.expression for point in result.points]
    assert any(head.startswith("Classical Adjectives") for head in headwords)
    assert any("古典文法" in head for head in headwords)
    # And a plain modern grammar lesson.
    assert any("The Particle" in head for head in headwords)


# ---------------------------------------------------------------------------
# The card's deliverables, written by the production extract path
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    """Extract into an isolated copy so the committed corpus is not mutated."""
    work = tmp_path_factory.mktemp("imabi-emit") / "imabi"
    shutil.copytree(_SOURCE_DIR, work)
    for artifact in (JSONL_NAME, COVERAGE_NAME):
        (work / artifact).unlink(missing_ok=True)
    result = ImabiExtractor(work).extract()
    return work, result


def test_extract_writes_one_jsonl_record_per_point(emitted):
    work, result = emitted
    path = work / JSONL_NAME
    assert path.is_file(), "extract must write the JSONL the card asks for"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(result.points)
    records = [json.loads(line) for line in lines]
    assert {r["source_id"] for r in records} == {p.source_id for p in result.points}
    for record in records:
        assert record["source"] == "imabi"
        assert record["provenance"]["attribution"] == ATTRIBUTION


def test_jsonl_keeps_a_trailing_newline_per_record(emitted):
    work, _ = emitted
    assert (work / JSONL_NAME).read_text(encoding="utf-8").endswith("\n")


def test_coverage_report_names_every_skip_and_its_reason(emitted):
    work, result = emitted
    report = (work / COVERAGE_NAME).read_text(encoding="utf-8")
    assert f"Lessons imported: {result.stats['importedLessons']}" in report
    assert f"Locked pages read: {result.stats['lockedPages']}" in report
    # Assert the per-page TABLE ROW carries the reason, not merely that the
    # reason string appears somewhere -- the summary counts list every reason
    # too, so a table with an empty reason column would otherwise pass.
    rows = [line for line in report.splitlines() if line.startswith("| ")]
    for skip in result.stats["skips"]:
        row = next(
            (r for r in rows if r.split("|")[1].strip() == str(skip["pageId"])), None
        )
        assert row is not None, f"page {skip['pageId']} has no coverage row"
        cells = [cell.strip() for cell in row.split("|")[1:-1]]
        assert cells[3] == str(skip["reason"]), (skip["pageId"], cells)
        assert cells[1], f"page {skip['pageId']} row has no title cell"
    # The report credits the source it covers.
    assert ATTRIBUTION in report


def test_coverage_fails_closed_when_a_page_is_unaccounted_for(result):
    # A report that silently lost a page must not be writable.
    with pytest.raises(ValueError):
        render_coverage(result, int(result.stats["lockedPages"]) + 1)
