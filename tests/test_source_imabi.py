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
from bugd.sources.imabi import ATTRIBUTION, ImabiExtractor

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
    assert result.stats["redistributable"] is True
    for point in result.points:
        prov = point.provenance
        assert prov["attribution"] == ATTRIBUTION
        assert prov["sourceLabel"] == "IMABI"
        assert prov["redistributable"] is True
        assert prov["licenseTier"] == "A"


def test_extract_fails_closed_when_a_locked_page_is_removed(tmp_path):
    work = tmp_path / "imabi"
    shutil.copytree(_SOURCE_DIR, work)

    lock = json.loads((work / "SOURCE.lock.json").read_text(encoding="utf-8"))
    page = next(p for p in lock["files"] if p.startswith("pages/"))
    (work / page).unlink()

    with pytest.raises(MalformedPayload):
        ImabiExtractor(work).extract()
