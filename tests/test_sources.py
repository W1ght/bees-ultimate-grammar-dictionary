"""Source registry + digest-locked source reading."""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from bugd.jsonio import dump_json
from bugd.sources import Extractor, ExtractResult, SourceLockError, load_source_lock
from bugd.sources.base import SOURCE_LOCK_NAME
from bugd.sources.registry import register_extractor, source_names


class _Fixture(Extractor):
    name = "unit-fixture"
    label = "Unit Fixture"


def _write_source(tmp_path, payload: bytes, *, digest=None, byte_count=None):
    directory = tmp_path / "unit-fixture"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.txt").write_bytes(payload)
    lock = {
        "source": "unit-fixture",
        "files": {
            "input.txt": {
                "sha256": digest or hashlib.sha256(payload).hexdigest(),
                "byteCount": byte_count if byte_count is not None else len(payload),
            }
        },
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    return directory


def test_extract_is_not_implemented_at_scaffold_time(tmp_path):
    with pytest.raises(NotImplementedError):
        _Fixture(tmp_path).extract()


def test_read_locked_bytes_accepts_matching_digest(tmp_path):
    directory = _write_source(tmp_path, b"hello")
    assert _Fixture(directory).read_locked_bytes("input.txt") == b"hello"


def test_read_locked_bytes_fails_closed_on_digest_mismatch(tmp_path):
    directory = _write_source(tmp_path, b"hello", digest="0" * 64)
    with pytest.raises(SourceLockError, match="digest mismatch"):
        _Fixture(directory).read_locked_bytes("input.txt")


def test_read_locked_bytes_fails_closed_on_byte_count_mismatch(tmp_path):
    directory = _write_source(tmp_path, b"hello", byte_count=99)
    with pytest.raises(SourceLockError, match="byte count"):
        _Fixture(directory).read_locked_bytes("input.txt")


def test_unlocked_file_is_refused(tmp_path):
    directory = _write_source(tmp_path, b"hello")
    (directory / "extra.txt").write_bytes(b"not locked")
    with pytest.raises(SourceLockError, match="not listed"):
        _Fixture(directory).read_locked_bytes("extra.txt")


def test_missing_lock_is_an_error(tmp_path):
    with pytest.raises(SourceLockError, match="missing source lock"):
        load_source_lock(tmp_path)


@pytest.mark.parametrize("unsafe", ["/abs.txt", "../escape.txt", "a\\b.txt", "./here.txt"])
def test_unsafe_locked_paths_are_refused(tmp_path, unsafe):
    lock = {"source": "x", "files": {unsafe: {"sha256": "0" * 64, "byteCount": 1}}}
    (tmp_path / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    with pytest.raises(SourceLockError, match="unsafe locked path"):
        load_source_lock(tmp_path)


@pytest.mark.parametrize(
    "entry",
    [
        {"byteCount": 1},
        {"sha256": "short", "byteCount": 1},
        {"sha256": "0" * 64},
        {"sha256": "0" * 64, "byteCount": -1},
        {"sha256": "0" * 64, "byteCount": True},
    ],
)
def test_malformed_lock_entries_are_refused(tmp_path, entry):
    lock = {"source": "x", "files": {"input.txt": entry}}
    (tmp_path / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    with pytest.raises(SourceLockError):
        load_source_lock(tmp_path)


def test_extract_result_rejects_misattributed_points(sample_point):
    with pytest.raises(Exception):
        ExtractResult(source="other", points=[sample_point])


def test_registry_rejects_duplicate_names():
    class First(Extractor):
        name = "dupe-check"

    class Second(Extractor):
        name = "dupe-check"

    register_extractor(First)
    assert "dupe-check" in source_names()
    with pytest.raises(ValueError, match="already registered"):
        register_extractor(Second)


def test_registry_rejects_unnamed_extractor():
    class Unnamed(Extractor):
        pass

    with pytest.raises(ValueError, match="does not declare a source name"):
        register_extractor(Unnamed)


def test_no_sources_registered_yet_by_import():
    """The scaffold ships no source logic; later cards register real sources."""
    import importlib

    import bugd.sources.registry as registry

    fresh = importlib.reload(registry)
    assert fresh.source_names() == []


def test_donna_toki_drops_the_appended_index_key_but_keeps_variant_lists():
    """The producer glues the entry's own reading onto its English prose.

    Measured over the corpus: 302 prose fields end with their reading right after
    a sentence terminator (`...conditions follow.あいだ`) -- that is the anchor key
    its site uses, and it rendered as a text-run bug. 48 other fields end with
    their reading as a deliberate variant list on its own line, which must stay.
    """
    from bugd.sources.donna_toki import _strip_trailing_index_key as strip

    assert strip("...conditions follow.あいだ", "あいだ") == "...conditions follow."
    assert strip("...sentences ❸ and ❹ ．からすると", "からすると") == "...sentences ❸ and ❹ ．"
    # Own-line variant lists are real content.
    assert strip("関連文法\n～ばいい／なければいい", "～ばいい／なければいい") == (
        "関連文法\n～ばいい／なければいい"
    )
    # No sentence terminator: the reading is part of the sentence.
    assert strip("often used with あいだ", "あいだ") == "often used with あいだ"
    assert strip(None, "あいだ") is None
    assert strip("あいだ", "あいだ") == "あいだ"


def test_edewakaru_drops_the_blog_ring_footer():
    """2,246 `にほんブログ村`, 1,057 `――以上――` and 492 `語学(日本語)ランキング` lines.

    The ranking caption was found by the UGD-14 round-6 visual gate, which
    reported it as "unstyled, purposeless text" appearing twice inside a grammar
    explanation. It occurs in exactly one form, always as its own line.
    """
    from bugd.sources.edewakaru import _strip_post_chrome

    body = "本文です。\nにほんブログ村\nにほんブログ村\n――以上――"
    assert _strip_post_chrome(body) == "本文です。"
    assert _strip_post_chrome(None) is None
    # A line that merely mentions the phrase inline is not a footer line.
    assert _strip_post_chrome("にほんブログ村に登録しました") == "にほんブログ村に登録しました"
    # The blog-ranking widget caption, in both bracket styles.
    assert _strip_post_chrome("本文です。\n語学(日本語)ランキング") == "本文です。"
    assert _strip_post_chrome("本文です。\n語学（日本語）ランキング") == "本文です。"
    # Real prose that happens to discuss rankings must survive.
    assert (_strip_post_chrome("ランキング上位の人たちは皆すごい")
            == "ランキング上位の人たちは皆すごい")


def test_a_line_opening_with_closing_punctuation_rejoins_the_line_above():
    """The producer puts a highlighted grammar point on its own line.

    So one sentence arrives as three lines and the card rendered
    `１時間悩んだ あげく 、買わなかった` -- reported by the UGD-14 round-8 visual gate as
    "unnatural extra spaces ... even before Japanese punctuation". A line starting
    with closing punctuation cannot begin a paragraph. Measured over the corpus:
    1,122 occurrences, 1,022 in edewakaru explanations.
    """
    from bugd.sources.community import clean

    assert clean("１時間悩んだ\nあげく\n、買わなかった") == "１時間悩んだ\nあげく、買わなかった"
    assert clean("「感極まる\n」は慣用表現です。") == "「感極まる」は慣用表現です。"
    assert clean("〜ていく\n。") == "〜ていく。"
    # A genuine paragraph break is preserved.
    assert clean("一つ目です。\n二つ目です。") == "一つ目です。\n二つ目です。"


def test_a_space_before_japanese_punctuation_is_removed():
    """Japanese has no inter-word space, so `だけに 、いい点が` is a producer artifact.

    16 occurrences across 3 sources, all defects.
    """
    from bugd.sources.community import clean

    assert clean("彼は野球選手なだけに 、体格がいい。") == "彼は野球選手なだけに、体格がいい。"
    assert clean("頼りないやつばかりだ 。") == "頼りないやつばかりだ。"
    # A space before the FULLWIDTH comma is left alone: this corpus uses it in
    # Latin enumerations (`as in ❹ ～ ❻ 、`) where the space can be intentional.
    assert clean("as in A ～ B ，next") == "as in A ～ B ，next"
    # Ordinary text is untouched.
    assert clean("これは丁寧です。") == "これは丁寧です。"


def test_the_chinese_line_detector_catches_the_producers_gloss_placeholder():
    """毎日のんびり日本語教師's Chinese column was leaking onto the card.

    The extractor already routes Chinese lines to `provenance["meaningZh"]`, but
    its detector recognised only a hand-listed set of Simplified characters, so
    487 of 1,990 packaged compact meaning lines and 124 of 718 sense labels still
    rendered as Chinese gloss lists. The UGD-14 round-8 visual gate reported
    `…左右 大概… …多 与…相同 和…一样` as an unreadable heading.

    The vocabulary cannot be enumerated (`非常…`, `按照…`, `极其…` were 870 more
    misses). The reliable signal is the producer's `…` slot placeholder: measured
    over the whole corpus, kana-free Latin-free Han-bearing lines containing `…`
    number 2,513 and every one is Chinese, while the source's Japanese glosses use
    the corpus's `〜` placeholder instead.
    """
    from bugd.sources.nihongo_no_sensei import is_chinese_line

    # The placeholder form the marker set missed.
    assert is_chinese_line("取决于…")
    assert is_chinese_line("非常…")
    assert is_chinese_line("与…相同 和…一样")
    assert is_chinese_line("…左右 大概…")
    # The Chinese enumeration comma.
    assert is_chinese_line("正因为有了Ａ，才有Ｂ的存在")
    # Simplified characters still work.
    assert is_chinese_line("这个问题")

    # Kana is decisive evidence of Japanese.
    assert not is_chinese_line("～によっては")
    assert not is_chinese_line("～次第で（は）")
    # An English gloss is not Chinese.
    assert not is_chinese_line("difficult to do")
    # All-shared-Han with no Chinese mark stays Japanese: under-claiming a
    # translation is safer than mislabelling Japanese text.
    assert not is_chinese_line("以前")
    assert not is_chinese_line("五段動詞")
    assert not is_chinese_line("名詞＋以前")
    # A line with no Han at all is not a Chinese gloss, even with an ellipsis --
    # `母：…` is a speaker label.
    assert not is_chinese_line("母：…")


def test_the_chinese_column_is_recognised_when_it_opens_with_its_ambiguous_line():
    """This producer sometimes writes its shortest Chinese gloss FIRST.

    The position pass only scanned forward from an already-confirmed Chinese line,
    so `一样` (`ながらに`) and `首屈一指` (`きっての`) stayed in the Japanese column and
    reached the card as the entry's compact meaning and sense heading. The UGD-14
    round-8 visual gate filed `…左右 大概… …多 与…相同 和…一样` as an unreadable
    heading. Measured over the source: 26 records change, and zero gain a line.
    """
    from bugd.sources.nihongo_no_sensei import _split_by_language

    # The reported defect: ambiguous line before the confirmed Chinese ones.
    assert _split_by_language("一样\n…状\n保持…的状态") == (None, "一样\n…状\n保持…的状态")
    assert _split_by_language("首屈一指\n第一的\n在…中最好的") == (
        None, "首屈一指\n第一的\n在…中最好的",
    )
    # The Japanese gloss after the Chinese column still survives.
    assert _split_by_language("不该有的\n作为…不应该有的行为\n～してはいけない") == (
        "～してはいけない", "不该有的\n作为…不应该有的行为",
    )

    # A record the producer wrote NO Chinese for is untouched: the pass requires a
    # confirmed Chinese line in the same field.
    assert _split_by_language("強調\n程度") == ("強調\n程度", None)

    # `によって` proves its enumerated column is Japanese by carrying kana in it, so
    # its kana-free sense labels are NOT absorbed...
    japanese, chinese = _split_by_language(
        "①根拠\n根据…／依据…／通过…\n②手段\n通过…／凭借…／靠…\n④受身（受身文の動作主）\n被…／由…"
    )
    assert japanese == "①根拠\n②手段\n④受身（受身文の動作主）"
    assert chinese == "根据…／依据…／通过…\n通过…／凭借…／靠…\n被…／由…"

    # ...but an enumerated line with no such evidence in its entry is treated like
    # any other ambiguous line, because enumerated Chinese exists too.
    assert _split_by_language("②表示后悔,遗憾\n…完／…了") == (
        None, "②表示后悔,遗憾\n…完／…了",
    )


def test_edewakaru_drops_a_chrome_run_glued_onto_real_text():
    """The producer sometimes appends the footer with NO newline before it.

    The whole-line rule could not see those, and 4 leaks reached the packaged
    banks of three successive candidates (`だって`, `なんで`, `みたいな`, `みたいに`),
    where a card ended with `…区別して覚えてください😊――以上――`. Measured over the
    source the glued form is 29 occurrences and is always a TAIL, so the rule is
    anchored at end-of-line and may repeat.
    """
    from bugd.sources.edewakaru import _strip_post_chrome

    assert (_strip_post_chrome("区別して覚えてください😊――以上――")
            == "区別して覚えてください😊")
    # A repeated run goes in one pass.
    assert _strip_post_chrome(
        "【イラストリスト】語学(日本語)ランキングにほんブログ村にほんブログ村――以上――"
    ) == "【イラストリスト】"
    # Trailing marker plus trailing whitespace.
    assert _strip_post_chrome("本文です。\nリスト）にほんブログ村") == "本文です。\nリスト）"

    # A line with NO marker is returned byte-identical, including its own
    # trailing whitespace -- the rule must not double as a whitespace trimmer.
    assert _strip_post_chrome("本文です。  ") == "本文です。  "
    # And an inline mention that is not a tail still survives.
    assert (_strip_post_chrome("にほんブログ村に登録しました。次の話です。")
            == "にほんブログ村に登録しました。次の話です。")


def test_edewakaru_strips_chrome_from_examples_too():
    """`_numbered_examples` was parsing the raw section, bypassing the stripper.

    That is why a chrome tail was still visible inside an EXAMPLE sentence on the
    `だって` and `なんで` cards rather than only in prose.
    """
    import pathlib

    from bugd.sources.edewakaru import EdewakaruExtractor
    from bugd.sources.yomitan_bank import TermRow

    body = "\n".join([
        "見出し｜JLPT　N３文法",
        "【意味】",
        "ほんとうの意味です。",
        "【例文】",
        "①これは本当の例文です。――以上――",
    ])
    row = TermRow(
        expression="わけだ",
        reading="わけだ",
        definition_tags="",
        deinflectors="",
        sequence=1,
        term_tags="中級",
        text=body,
    )
    point = EdewakaruExtractor(pathlib.Path(".")).parse(row)
    assert point is not None
    assert point.examples, "the example must survive the strip"
    for example in point.examples:
        assert "――以上――" not in example.japanese
    assert "これは本当の例文です。" in point.examples[0].japanese


def test_edewakaru_strips_chrome_from_every_prose_field():
    """`structure` was the one prose field bypassing the chrome stripper.

    After the ranking caption was added to the footer set, 4 of the original 492
    occurrences survived re-extraction because `structure` was passed to `clean`
    directly. Asserts the extracted BEHAVIOUR: no prose field a card renders may
    contain a chrome line.
    """
    from bugd.sources.edewakaru import _POST_CHROME, EdewakaruExtractor
    from bugd.sources.yomitan_bank import TermRow

    chrome = "語学(日本語)ランキング"
    assert chrome in _POST_CHROME
    body = "\n".join([
        "見出し｜JLPT　N３文法",
        "【意味】",
        "ほんとうの意味です。",
        chrome,
        "【接続】",
        "Ｖ（辞書形）＋わけだ",
        chrome,
        "【説明】",
        "ほんとうの解説です。",
        chrome,
    ])
    row = TermRow(
        expression="わけだ",
        reading="わけだ",
        definition_tags="",
        deinflectors="",
        sequence=1,
        term_tags="中級",
        text=body,
    )
    point = EdewakaruExtractor(pathlib.Path(".")).parse(row)
    assert point is not None
    for field in ("meaning", "structure", "explanation"):
        value = getattr(point, field) or ""
        assert chrome not in value, f"{field} still carries site chrome: {value!r}"
    # The real content around the chrome must survive.
    assert "ほんとうの解説です。" in (point.explanation or "")


def test_edewakaru_keeps_a_paraphrase_that_opens_with_a_bold_span():
    """A `→` rephrasing whose first word is bold lands the arrow alone on its line.

    `read_term_bank` puts every glossary node on its own line, so when edewakaru's
    `→` paraphrase opens with a bold grammar-point span the arrow is left on its own
    line (`…泣いてしまった` / `→` / `とても` / …). The old parser only opened a
    rephrasing when text sat on the arrow's own line, so a bare `→` was dropped and
    the paraphrase words fused onto the specimen:
    `嬉しさのあまり泣いてしまったとても嬉しいので泣いてしまった` -- the run-on UGD-08c filed on
    あまり and に反して (findings 1, 2, 4, 5, 13) and the clipped `→たばこは高いし 体に悪いし、`
    (findings 9, 12). Measured over edewakaru: 158 arrow-alone lines / 61 fields.

    The property: the specimen and its paraphrase are separated by `\\n→`, the
    paraphrase carries its full text, and no source characters are lost.
    """
    from bugd.sources.edewakaru import _numbered_examples

    # The arrow sits alone on its line; the paraphrase words follow it. Emulates the
    # node-per-line flattening of `のあまり`/`とても`/`ので` bold spans.
    body = "\n".join([
        "①嬉しさ", "のあまり", "泣いてしまった",
        "→", "とても", "嬉しい", "ので", "泣いてしまった",
    ])
    examples = _numbered_examples(body, highlights=("のあまり",))
    assert len(examples) == 1
    # The specimen keeps its own text; the paraphrase is a separate `→` line with
    # its COMPLETE text -- not truncated at the first bold span, not fused on.
    assert examples[0].japanese == "嬉しさのあまり泣いてしまった\n→とても嬉しいので泣いてしまった"

    # A `→` that DOES carry its own text still works exactly as before.
    same_line = "\n".join(["①予想に反して難しくなかった", "→予想とは違って難しくなかった"])
    assert _numbered_examples(same_line, ())[0].japanese == (
        "予想に反して難しくなかった\n→予想とは違って難しくなかった"
    )

    # Two circled examples, the second's paraphrase also arrow-alone: both split.
    two = "\n".join([
        "①急いだ", "あまり", "スマホを忘れた", "→", "とても", "急いだので", "スマホを忘れた",
        "②きれいな", "あまり", "感動した", "→", "とても", "きれいだったので", "感動した",
    ])
    got = _numbered_examples(two, ())
    assert [e.japanese for e in got] == [
        "急いだあまりスマホを忘れた\n→とても急いだのでスマホを忘れた",
        "きれいなあまり感動した\n→とてもきれいだったので感動した",
    ]
