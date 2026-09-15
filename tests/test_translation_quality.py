"""The gate that keeps a degraded machine translation out of the dictionary.

Every case here is drawn from what v2026.09.14.4 actually shipped: 99.4% of
IMABI's 494 Chinese explanations, 100% of Yokubi's 132 and 43.5% of DoJG's 1,545
carried placeholder debris, a decoder repetition loop, or a truncation.
"""

from __future__ import annotations

import pytest

from bugd.model import Example, GrammarPoint
from bugd.banks import _example_translation_zh, _translation_zh
from bugd.translation_quality import (
    degradation,
    has_placeholder_debris,
    protected_spans,
    split_protected,
)


# --------------------------------------------------------------------------
# what a translation is allowed to do to its source
# --------------------------------------------------------------------------


def test_a_faithful_translation_passes():
    source = "The pattern 〜はずだ expresses what should be the case."
    assert degradation(source, "句型 〜はずだ 表示按理说应该如此的情况。") is None


def test_shipped_placeholder_debris_is_rejected():
    """The exact failure: the sentinel was re-spelled, so `restore` missed it."""
    source = "Adverbs that have a 促音 and end in り."
    assert degradation(source, "有 ZQQJPN000Q 且以 ZQJPN0001Q 结尾的副词。") == "placeholder-leak"


@pytest.mark.parametrize(
    "debris",
    [
        "ZXQJPN00003Q",  # intact sentinel: restore never ran
        "ZQQJPN00014",  # a letter dropped
        "Z~JPN00111Q",  # a letter re-spelled
        "JPN00079Q",  # the prefix eaten
    ],
)
def test_every_observed_respelling_of_the_sentinel_is_caught(debris):
    assert has_placeholder_debris(f"这里按理说是 {debris} 的意思。")


def test_losing_the_japanese_being_explained_is_rejected():
    """`赞 贾 宾 夸 Q` -- the sentinel transliterated character by character.

    No recognisable sentinel survives, so the debris check cannot see it. What
    gives it away is that the pattern the entry exists to explain is gone.
    """
    source = "ただの | Noun |\n| ただの先生 | An ordinary teacher |"
    assert degradation(source, "赞 贾 宾 夸 Q 名 词 | | |普通老师") == "lost-source-spans"


def test_a_decoder_repetition_loop_is_rejected():
    source = "The following chart shows the most common abbreviations in Japanese."
    assert degradation(source, "重音" * 60) == "runaway-repetition"


def test_repetition_the_source_itself_has_is_kept():
    """A source table repeats; a faithful translation of it must be allowed to."""
    source = "yes " * 40
    assert degradation(source, "是 " * 40) is None


def test_a_translation_that_stopped_early_is_rejected():
    source = (
        "No matter how many apologetic feelings you have inside, if you don't have "
        "it take form, then it will not come across to the other person."
    )
    assert degradation(source, "不论内心有多少歉意,") == "truncated"


def test_an_absent_translation_is_not_a_degraded_one():
    assert degradation("anything at all, at length", "") is None


# --------------------------------------------------------------------------
# holding the protected runs out of the model instead of restoring them
# --------------------------------------------------------------------------


def test_protected_spans_are_the_japanese_links_and_markup():
    spans = protected_spans("See <b>〜はずだ</b> at https://yoku.bi/x for と usage.")
    assert "<b>" in spans and "〜はずだ" in spans and "https://yoku.bi/x" in spans
    # A single-character run is too common to be evidence of loss.
    assert "と" not in spans


def test_splitting_loses_no_character():
    text = "Use 〜ようにする when someone makes sure that 話す happens.\nSee <i>note</i>."
    assert "".join(piece for _, piece in split_protected(text)) == text


def test_the_japanese_is_never_handed_to_the_translator():
    pieces = split_protected("The word 促音 means a geminate.")
    translatable = [piece for translate, piece in pieces if translate]
    assert not any("促音" in piece for piece in translatable)
    assert (False, "促音") in pieces


# --------------------------------------------------------------------------
# the card drops what the gate rejects, and falls back to the source's English
# --------------------------------------------------------------------------


def _point(**extra) -> GrammarPoint:
    return GrammarPoint(
        source="imabi",
        source_id="x",
        expression="〜はずだ",
        row_uid="imabi:1",
        **extra,
    )


def test_a_degraded_field_translation_is_not_rendered():
    point = _point(
        explanation="The pattern 〜はずだ expresses what should be the case.",
        provenance={"translationZh": {"explanation": "句型 ZQQJPN000Q 表示 " + "完全; " * 30}},
    )
    assert _translation_zh(point, "explanation") == ""


def test_a_sound_field_translation_is_still_rendered():
    point = _point(
        explanation="The pattern 〜はずだ expresses what should be the case.",
        provenance={"translationZh": {"explanation": "句型 〜はずだ 表示按理说应该如此。"}},
    )
    assert _translation_zh(point, "explanation") == "句型 〜はずだ 表示按理说应该如此。"


def test_a_publisher_authored_chinese_gloss_is_never_gated():
    """`meaningZh` is 毎日のんびり日本語教師's own column, not this build's output."""
    point = _point(meaning="ある動作をする", provenance={"meaningZh": "做某个动作"})
    assert _translation_zh(point, "meaning") == "做某个动作"


def test_a_degraded_example_gloss_is_not_rendered():
    point = _point(
        examples=(Example(japanese="泳ぐことができる。", english="I can swim."),),
        provenance={"translationZh": {"examples": {"泳ぐことができる。": "我 ZXQJPN00002Q 游泳。"}}},
    )
    assert _example_translation_zh(point, "泳ぐことができる。", 0, "I can swim.") == ""


def test_a_sound_example_gloss_is_still_rendered():
    point = _point(
        examples=(Example(japanese="泳ぐことができる。", english="I can swim."),),
        provenance={"translationZh": {"examples": {"泳ぐことができる。": "我会游泳。"}}},
    )
    assert _example_translation_zh(point, "泳ぐことができる。", 0, "I can swim.") == "我会游泳。"
