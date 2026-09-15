"""Regression for the twelve UGD-11d-B absolute-rule hedges.

Card ``t_9b1f732e`` filed twelve merged cards where one source stated an ABSOLUTE
usage rule (必ず… / 〜しか使えません / いけません / ❌… / なければいけません) that another
source's sanctioned example directly violated — a learner saw the rule and a live
counterexample to it on the same card with no guidance which to follow.

The remedy is a per-source hedge applied at the extraction layer
(``bugd.source_corrections.HedgeAbsolute``): the source's own prose stays
byte-attributed to it, but the absolute operator is replaced in place with a
lowered-modality restatement plus an inline note that other sources disagree. The
locked source bytes are never touched, so a re-extract reproduces the hedged
record deterministically.

These tests run the REAL community extractors against the REAL locked source
directories and assert, per item, that on the source's rendering row the absolute
operator is GONE and the hedged (still-attributed) statement is PRESENT. The
rendering row is located by the hedged text itself rather than by first-wins
source_id lookup, because UGD-11d proved source_id is not unique (e.g. edewakaru
carries four ``なり`` senses, only one of which states the same-subject rule).
"""

from __future__ import annotations

import pathlib

import pytest

from bugd.source_corrections import HedgeAbsolute, SourceCorrectionError
from bugd.sources.donna_toki import DonnaTokiExtractor
from bugd.sources.edewakaru import EdewakaruExtractor
from bugd.sources.nihongo_no_sensei import NihongoNoSenseiExtractor

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES = REPO / "data" / "sources"

from conftest import requires_source  # noqa: E402

_needs_sources = requires_source("edewakaru")

_EXTRACTORS = {
    "edewakaru": EdewakaruExtractor,
    "nihongo_no_sensei": NihongoNoSenseiExtractor,
    "donna_toki": DonnaTokiExtractor,
}

_POINTS_CACHE: dict[str, list] = {}


def _points(source: str) -> list:
    if source not in _POINTS_CACHE:
        cls = _EXTRACTORS[source]
        _POINTS_CACHE[source] = list(cls(SOURCES / cls.name).extract().points)
    return _POINTS_CACHE[source]


# (item, source, source_id, absolute_marker_that_must_be_gone,
#  hedged_fragment_that_must_be_present, tendency_note_that_must_be_present)
# The absolute marker and the hedged fragment are verbatim substrings of the
# source's own explanation prose after / before the hedge.
ITEMS = [
    (
        "B1",
        "edewakaru",
        "あげく",
        "よくない結果になったことに使います",
        "よくない結果になったことに使う傾向があります",
        "他の辞書はよい結果の例も認めます",
    ),
    (
        "B2",
        "edewakaru",
        "か",
        "後ろには必ず「た形」がくる",
        "後ろには多くの場合「た形」がくる",
        "他の辞書は非過去の例も挙げています",
    ),
    (
        "B4",
        "edewakaru",
        "が早いか",
        "使うと不自然になります",
        "使うと不自然になりやすいとされます",
        "他の辞書はそうした例も認めます",
    ),
    (
        "B5",
        "nihongo_no_sensei",
        "が早いか",
        "この文法は過去のことにしか使えません。",
        "この文法は主に過去のことに使われます。",
        "他の辞書は非過去の例も挙げています",
    ),
    (
        "B6",
        "edewakaru",
        "くせに",
        "人に使う（動物であればOKな場合もある）",
        "主に人（動物であればOKな場合もある）を対象にする傾向があります",
        "他の辞書は物事を主語にする例も認めます",
    ),
    (
        "B9",
        "nihongo_no_sensei",
        "すら",
        "後件には否定形が呼応します。",
        "後件には否定形が呼応する傾向があります。",
        "肯定形の後件が見られます",
    ),
    (
        "B10",
        "nihongo_no_sensei",
        "せいで",
        "良くない結果を述べます",
        "良くない結果を述べる傾向があります",
        "他の辞書はよい結果の例も認めます",
    ),
    (
        "B13",
        "edewakaru",
        "なり",
        "主語は同じでなければいけません",
        "主語は同じであることが多いです",
        "他の辞書は主語が異なる例も挙げています",
    ),
    (
        "B14",
        "donna_toki",
        "に至っては",
        "マイナス評価の例がいくつかある中で",
        "いくつかの例がある中で",
        "他の辞書は中立的な極端例も挙げています",
    ),
    (
        "B18",
        "donna_toki",
        "ようにも",
        "その可能動詞である。",
        "その可能動詞であることが多い。",
        "可能形の否定形がくる場合も挙げています",
    ),
    (
        "B19",
        "nihongo_no_sensei",
        "わ",
        "良いことにも使えますが、",
        "どちらかというと悪い意味の用法が多めに感じます。",
        "良い意味での用法は確認できません",
    ),
    (
        "B20",
        "edewakaru",
        "をものともせずに",
        "話し手自身のことには使えません",
        "話し手自身のことには使いにくいとされます",
        "他の辞書は一人称の例も認めます",
    ),
]


def _rendering_point(source: str, source_id: str, hedged_fragment: str):
    """The extracted point that actually carries the hedged prose.

    Located by the hedged fragment, not by first-wins source_id, because a
    single source_id can span several senses (only one states the rule).
    """
    candidates = [
        p
        for p in _points(source)
        if p.source_id == source_id
        and p.explanation
        and hedged_fragment in p.explanation
    ]
    assert candidates, (
        f"no {source} point with source_id {source_id!r} carries the hedged "
        f"fragment {hedged_fragment!r}"
    )
    return candidates[0]


@_needs_sources
@pytest.mark.parametrize(
    "finding,source,source_id,absolute,hedged,note",
    ITEMS,
    ids=[i[0] for i in ITEMS],
)
def test_absolute_rule_is_hedged(finding, source, source_id, absolute, hedged, note):
    point = _rendering_point(source, source_id, hedged)
    explanation = point.explanation
    # (1) the absolute phrasing is gone from this source's rendered prose…
    assert absolute not in explanation, (
        f"{finding}: absolute marker {absolute!r} still present in "
        f"{source}#{source_id}"
    )
    # (2) …but the statement survives, re-cast as this source's tendency…
    assert hedged in explanation, (
        f"{finding}: hedged statement {hedged!r} missing from {source}#{source_id}"
    )
    # (3) …with the inline cross-source note, so it stays attributed and the card
    # no longer presents an unqualified rule beside a live counterexample.
    assert note in explanation, (
        f"{finding}: cross-source note {note!r} missing from {source}#{source_id}"
    )
    # provenance preserved: the record still belongs to its original source.
    assert point.source == source


@_needs_sources
def test_all_twelve_items_applied():
    """Every filed item resolves to a real, hedged rendering row (no silent skips)."""
    for finding, source, source_id, _absolute, hedged, _note in ITEMS:
        _rendering_point(source, source_id, hedged)  # raises if missing


def test_hedge_passes_through_rows_without_the_anchor(sample_point):
    """A sibling row under a shared source_id that lacks the anchor is untouched.

    edewakaru's four ``なり`` senses share one source_id; only one states the
    same-subject rule. The hedge must no-op on the others rather than fail closed.
    """
    hedge = HedgeAbsolute("NOT-IN-THIS-POINT", "x", "", 1, "TEST")
    assert hedge.apply(sample_point) is sample_point


def test_hedge_fails_closed_when_hedged_text_keeps_the_absolute():
    """A malformed hedge that leaves the absolute operator in place is rejected."""
    bad = HedgeAbsolute("必ずた形", "やはり必ずた形", "必ず", 1, "TEST")
    # sample_point is not needed: the structural guard fires before any row match.
    from bugd.model import GrammarPoint

    point = GrammarPoint(
        source="x",
        source_id="y",
        expression="z",
        explanation="必ずた形がくる",
    )
    with pytest.raises(SourceCorrectionError, match="still contains the absolute"):
        bad.apply(point)
