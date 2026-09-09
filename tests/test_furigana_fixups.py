"""Tests for the normalize-stage furigana / JLPT fix-up table (UGD-11a).

The ``raw`` fixtures below are the exact substrings pulled from the two source
decks' ``collection.anki21b`` HTML, so these assert against real content, not
invented examples.
"""

from __future__ import annotations

from bugd.furigana_fixups import (
    RUBY_FIXUPS,
    apply_ruby_fixups,
    normalize_furigana,
    normalize_jlpt_field,
    repair_empty_ruby,
)


# --- ruby-pair typo fix-ups (verified raw fragments) --------------------------

def test_omou_typo_fixed():
    raw = "いたほうがいいと<ruby>思<rt>あも</rt></ruby>います。"
    assert normalize_furigana(raw) == "いたほうがいいと<ruby>思<rt>おも</rt></ruby>います。"


def test_watashi_typo_fixed():
    raw = "、<ruby>私<rt>またし</rt></ruby>のコレクションは"
    assert normalize_furigana(raw) == "、<ruby>私<rt>わたし</rt></ruby>のコレクションは"


def test_manabu_typo_fixed():
    raw = "などを<ruby>学<rt>なな</rt></ruby>ぶことができました。"
    assert normalize_furigana(raw) == "などを<ruby>学<rt>まな</rt></ruby>ぶことができました。"


def test_taishite_typo_fixed_and_does_not_touch_tsukau():
    # Same clause carries a WRONG 対(つか) and a CORRECT 使(つか). Only 対 is fixed.
    raw = "<ruby>動詞<rt>どうし</rt></ruby>に<ruby>対<rt>つか</rt></ruby>しても<ruby>使<rt>つか</rt></ruby>う"
    out = normalize_furigana(raw)
    assert "<ruby>対<rt>たい</rt></ruby>" in out
    assert "<ruby>使<rt>つか</rt></ruby>" in out  # legitimate pair untouched


def test_tsukaikata_typo_fixed():
    raw = "の<ruby>使<rt>かた</rt></ruby>い<ruby>方<rt>かた</rt></ruby>を"
    out = normalize_furigana(raw)
    assert "<ruby>使<rt>つか</rt></ruby>" in out
    assert "<ruby>方<rt>かた</rt></ruby>" in out  # 方(かた) is correct, untouched


def test_every_declared_fixup_actually_rewrites():
    for (base, wrong), right in RUBY_FIXUPS.items():
        src = f"x<ruby>{base}<rt>{wrong}</rt></ruby>y"
        assert apply_ruby_fixups(src) == f"x<ruby>{base}<rt>{right}</rt></ruby>y"


def test_fixups_are_idempotent():
    raw = "いと<ruby>思<rt>あも</rt></ruby>い、<ruby>私<rt>またし</rt></ruby>は"
    once = normalize_furigana(raw)
    assert normalize_furigana(once) == once


# --- documented FALSE POSITIVES are left alone --------------------------------

def test_bimi_oishii_left_unchanged():
    # 美味<rt>おい</rt> + okurigana し… is correct jukujikun and must NOT change.
    raw = "とても<ruby>美味<rt>おい</rt></ruby>しい。"
    assert normalize_furigana(raw) == raw


def test_contracted_compounds_left_unchanged():
    for frag in (
        "<ruby>二日酔<rt>ふつかよ</rt></ruby>い",
        "<ruby>打合<rt>うちあわ</rt></ruby>せ",
        "<ruby>組合<rt>くみあわ</rt></ruby>せ",
        "<ruby>一人暮<rt>ひとりぐら</rt></ruby>し",
        "<ruby>見出<rt>みいだ</rt></ruby>せない",
    ):
        assert normalize_furigana(frag) == frag


def test_correct_ruby_never_touched():
    raw = "<ruby>初<rt>はじ</rt></ruby>めて<ruby>雪<rt>ゆき</rt></ruby>を<ruby>見<rt>み</rt></ruby>た"
    assert normalize_furigana(raw) == raw


# --- empty / missing <rt> repair ----------------------------------------------

def test_missing_rt_unwrapped_to_surface():
    raw = "この<ruby>漢字</ruby>の<ruby>読</ruby>み<strong>方</strong>"
    assert repair_empty_ruby(raw) == "この漢字の読み<strong>方</strong>"


def test_explicit_empty_rt_unwrapped():
    assert repair_empty_ruby("<ruby>方法<rt></rt></ruby>") == "方法"
    assert repair_empty_ruby("<ruby>料理<rt>  </rt></ruby>") == "料理"


def test_leaked_particle_base_preserved_as_text():
    # 健康の had the particle inside the base; unwrap keeps the surface exactly.
    assert repair_empty_ruby("<ruby>健康の</ruby>ために") == "健康のために"


def test_all_cited_empty_ruby_bases():
    for base in (
        "方法", "読", "料理", "同", "同時", "勉強", "見",
        "電話", "車", "朝", "食", "大学", "相手", "健康の",
    ):
        assert repair_empty_ruby(f"<ruby>{base}</ruby>") == base


def test_empty_ruby_repair_leaves_valid_ruby_alone():
    raw = "<ruby>方<rt>かた</rt></ruby>"
    assert repair_empty_ruby(raw) == raw


def test_empty_ruby_repair_idempotent():
    raw = "<ruby>方法</ruby>と<ruby>読</ruby>"
    once = repair_empty_ruby(raw)
    assert repair_empty_ruby(once) == once == "方法と読"


# --- JLPT field normalization -------------------------------------------------

def test_jlpt_nested_wrapper_divs_stripped():
    assert normalize_jlpt_field("<div><div><div>N3</div></div></div>") == ("N3", None)


def test_jlpt_level_plus_footnote_split():
    level, note = normalize_jlpt_field("N4<br>※N4では意味①のみ扱う。")
    assert level == "N4"
    assert note == "N4では意味①のみ扱う。"


def test_jlpt_plain_level():
    assert normalize_jlpt_field("N5") == ("N5", None)
    assert normalize_jlpt_field("  N2  ") == ("N2", None)


def test_jlpt_empty_and_none():
    assert normalize_jlpt_field("") == (None, None)
    assert normalize_jlpt_field("<div></div>") == (None, None)
    assert normalize_jlpt_field(None) == (None, None)


def test_jlpt_unknown_level_becomes_note_not_badge():
    # Not one of N1..N5 -> no badge; text preserved as a note.
    level, note = normalize_jlpt_field("N6")
    assert level is None
    assert note == "N6"
