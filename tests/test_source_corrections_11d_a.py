"""Regression for the eight Class-A source data corrections (UGD-11d-A).

Card ``t_62bd276f`` filed eight cross-source data defects: in each one, a single
source's field was wrong (a typo, a paste from a neighbouring entry, or a formula
that the source's own examples violate) while every other contributing source
agreed on the correct value. A learner reading the merged card could derive an
ungrammatical form.

The corrections live at the extraction layer as a recorded, replayable per-source
correction table (``bugd.source_corrections``) applied to each ``GrammarPoint``
right after its parser produces it — the acquired source bytes stay locked and
byte-identical. These tests run the REAL extractors against the REAL locked source
directories and assert, per defect, that the wrong string is gone and the right
string is present in the affected source's extracted point. One test per defect
A1–A8, plus a guard that unaffected records are untouched.
"""

from __future__ import annotations

import pathlib

import pytest

from bugd.source_corrections import (
    ReplaceIn,
    SetExpression,
    SourceCorrectionError,
    correct_point,
)
from bugd.sources.dojg import DojgExtractor
from bugd.sources.nihongo_net import NihongoNetExtractor

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES = REPO / "data" / "sources"

from conftest import requires_source  # noqa: E402

_needs_sources = requires_source("nihongo_net")


def _index(extractor_cls) -> tuple[dict[str, object], list]:
    """Extract one source and index its points by source_id (first wins)."""
    result = extractor_cls(SOURCES / extractor_cls.name).extract()
    by_id: dict[str, object] = {}
    for point in result.points:
        by_id.setdefault(point.source_id, point)
    return by_id, result.points


@pytest.fixture(scope="module")
def nihongo_net():
    return _index(NihongoNetExtractor)


@pytest.fixture(scope="module")
def dojg():
    return _index(DojgExtractor)


# ---------------------------------------------------------------------------
# A1 — dojg#にほかならない misspells the headword
# ---------------------------------------------------------------------------
@_needs_sources
def test_A1_nihokaranai_spelling(dojg):
    by_id, _ = dojg
    point = by_id["にほかならない"]
    # wrong forms gone from the structure table…
    assert "にはかならない" not in point.structure
    # …and all six occurrences now read にほかならない (the structure table has three
    # sub-patterns, each writing the form twice: header row + glossed example).
    assert point.structure.count("にほかならない") == 6
    # the one corrupted example (ことにほならない) is repaired.
    joined = "".join(ex.japanese for ex in point.examples)
    assert "ことにほならない" not in joined
    assert "ことにほかならない" in joined


# ---------------------------------------------------------------------------
# A2 — nihongo_net#でしょう licenses ×雨だでしょう
# ---------------------------------------------------------------------------
@_needs_sources
def test_A2_deshou_noun_attaches_bare(nihongo_net):
    by_id, _ = nihongo_net
    point = by_id["でしょう"]
    assert "※Nだ + でしょう" not in point.structure
    assert "※Nでしょう" in point.structure
    # bare noun attachment (the correct rule) is preserved.
    assert "N（普通形） + でしょう" in point.structure


# ---------------------------------------------------------------------------
# A3 — nihongo_net#かどうか licenses ×便利だかどうか
# ---------------------------------------------------------------------------
@_needs_sources
def test_A3_kadouka_no_da_before_kadouka(nihongo_net):
    by_id, _ = nihongo_net
    point = by_id["かどうか"]
    assert "だかどうか" not in point.structure
    assert "ナA（語幹）（である／なの）かどうか、〜" in point.structure
    assert "N（である／なの）かどうか、〜" in point.structure


# ---------------------------------------------------------------------------
# A4 — nihongo_net#さえ verb row says ×さえあれば
# ---------------------------------------------------------------------------
@_needs_sources
def test_A4_sae_verb_row_is_saesureba(nihongo_net):
    by_id, _ = nihongo_net
    point = by_id["さえ"]
    assert "V（ます形）ます + さえあれば" not in point.structure
    assert "V（ます形）ます + さえすれば" in point.structure
    # さえあれば survives ONLY on the non-verb rows (イAく／ナAで／N).
    assert "イAく + さえあれば" in point.structure
    assert "N + さえあれば" in point.structure


# ---------------------------------------------------------------------------
# A5 — nihongo_net#ないでもない pasted from 〜ものでもない
# ---------------------------------------------------------------------------
@_needs_sources
def test_A5_naidemonai_structure(nihongo_net):
    by_id, _ = nihongo_net
    point = by_id["ないでもない"]
    assert "ものでもない" not in point.structure
    assert point.structure.count("ないでもない") == 4
    assert "V（ナイ形） + ないでもない" in point.structure


# ---------------------------------------------------------------------------
# A6 — nihongo_net#かいがあって (and #かいもなく) structure names あげく
# ---------------------------------------------------------------------------
@_needs_sources
@pytest.mark.parametrize("source_id", ["かいがあって", "かいもなく"])
def test_A6_kaigaatte_structure(nihongo_net, source_id):
    by_id, _ = nihongo_net
    point = by_id[source_id]
    assert "あげく" not in point.structure
    assert "する動詞のNの + かいがあって" in point.structure


# ---------------------------------------------------------------------------
# A7 — nihongo_net#に至るまで is really a 〜に至る entry
# ---------------------------------------------------------------------------
@_needs_sources
def test_A7_niitarumade_rehomed_to_niitaru(nihongo_net):
    by_id, points = nihongo_net
    # the record keeps its source_id (provenance) but is re-homed to に至る,
    # so it no longer merges into the range-meaning に至るまで card.
    point = by_id["に至るまで"]
    assert point.expression == "に至る"
    # no nihongo_net point still claims the に至るまで headword.
    assert not any(p.expression == "に至るまで" for p in points)


# ---------------------------------------------------------------------------
# A8 — dojg#ことは noun rows drop こと
# ---------------------------------------------------------------------------
@_needs_sources
def test_A8_kotowa_noun_rows_keep_koto(dojg):
    by_id, _ = dojg
    point = by_id["ことは"]
    assert "| いい人はいい人{だ/です} |" not in point.structure
    assert "| いい人であることはいい人{だ/です} |" in point.structure
    assert "| いい人だったことは人{だった/でした} |" not in point.structure
    assert "| いい人だったことはいい人{だった/でした} |" in point.structure
    # the already-correct な-adjective row is left untouched.
    assert "静かなことは静か{だ/です}" in point.structure


# ---------------------------------------------------------------------------
# Guards on the correction machinery itself.
# ---------------------------------------------------------------------------
def test_uncorrected_point_passes_through_identically(sample_point):
    assert correct_point(sample_point) is sample_point


def test_replace_in_fails_closed_on_count_drift(sample_point):
    bad = ReplaceIn("structure", "NOT-PRESENT", "x", 1, "TEST")
    with pytest.raises(SourceCorrectionError, match="expected 1 occurrence"):
        bad.apply(sample_point)


def test_set_expression_fails_closed_on_wrong_headword(sample_point):
    bad = SetExpression("に至る", "SOMETHING-ELSE", "TEST")
    with pytest.raises(SourceCorrectionError, match="expected expression"):
        bad.apply(sample_point)
