"""Structure-form audit: a formation line that spells a corrupted headword.

The audit is advisory (Japanese morphology is too dense for a fail-closed
edit-distance gate), so these tests pin its PROPERTY rather than a suspect count:
it fires on an internal one-kana corruption of the headword that appears in no
example, and it stays silent for the legitimate cases that make a naive gate
useless — a form the examples actually use, and a final-cell inflection.
"""

from __future__ import annotations

from bugd.model import Example, GrammarPoint
from bugd.structure_audit import audit_point


def _point(structure: str, expression: str, example: str) -> GrammarPoint:
    return GrammarPoint(
        source="dojg",
        source_id=expression,
        expression=expression,
        structure=structure,
        examples=(Example(japanese=example),),
    )


def test_fires_on_internal_one_kana_corruption_absent_from_examples():
    # にはかならない (は for ほ) in the 接続 line while every example uses にほかならない.
    point = _point(
        structure="名詞 にはかならない",
        expression="にほかならない",
        example="それは冗談にほかならない。",
    )
    suspects = audit_point(point)
    assert [s["structure_form"] for s in suspects] == ["にはかならない"]


def test_silent_when_the_structure_form_is_actually_used_in_an_example():
    # A form the card's own example uses is by definition not a phantom variant,
    # even if it is edit-distance 1 from the headword.
    point = _point(
        structure="ないこと はない",  # a related, attested shorter form
        expression="ないことはない",
        example="できないことはないが、難しい。ないことはある。",
    )
    assert audit_point(point) == []


def test_silent_on_final_cell_inflection():
    # にわたる vs にわたった differ only at the final okurigana cell — a paradigm
    # cell the point teaches, not a typo. Must not be flagged.
    point = _point(
        structure="名詞 にわたった 名詞",
        expression="にわたって",
        example="三日間にわたって行われた。",
    )
    # にわたった differs from にわたって at the final positions, so it is not an
    # internal single-kana substitution and is not reported.
    assert audit_point(point) == []


def test_silent_when_headword_is_not_attested_on_the_card():
    # If the correct headword appears nowhere else, we cannot claim the structure
    # form is a corruption OF it — no false accusation on sparse cards.
    point = _point(
        structure="名詞 にはかならない",
        expression="にほかならない",
        example="意味の分からない例文。",
    )
    assert audit_point(point) == []


def test_silent_on_short_kana_or_kanji_headwords():
    # Below the 4-kana floor a single-kana coincidence is too likely; kanji
    # headwords are out of scope for this kana-typo signature.
    short = _point(structure="のに", expression="ので", example="行くので。行くのに。")
    assert audit_point(short) == []
    kanji = GrammarPoint(
        source="dojg", source_id="結果", expression="結果",
        structure="Vinformal past 結果",
        examples=(Example(japanese="話した結果。"),),
    )
    assert audit_point(kanji) == []
