"""Source registry + digest-locked source reading."""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

import pytest

from bugd.jsonio import MalformedPayload, dump_json
from bugd.model import GrammarPoint
from bugd.sources import Extractor, ExtractResult, SourceLockError, load_source_lock
from bugd.sources.base import SOURCE_LOCK_NAME, DuplicateRowIdentity
from bugd.sources.registry import register_extractor, source_names

REPO = pathlib.Path(__file__).resolve().parents[1]


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


def test_the_registry_discovers_every_source_in_a_fresh_interpreter():
    """Registration must not depend on someone remembering to import a module.

    This replaces `test_no_sources_registered_yet_by_import`, a scaffold-era
    tripwire that asserted a freshly reloaded registry knew NO sources. It kept
    passing after five extractors landed, because reloading the module discards
    the registry while the source modules stay cached in `sys.modules`, so their
    `@register_extractor` decorators never ran again. That hid the actual defect:
    nothing in the shipped code imported the concrete source modules, so
    `bugd.cli extract` reported `{"sources": {}, "total": 0}` and exited 0 in a
    complete checkout, and only throwaway scripts with hard-coded
    `import bugd.sources.dojg` lines ever produced the real artifacts.

    Measured in a SUBPROCESS on purpose: a fresh interpreter is what `make
    extract` actually gets, and it is the only way to observe first-import
    behaviour. Reloading in-process cannot see it.
    """
    probe = (
        "from bugd.pipeline import run_extract;"
        "from bugd.sources import source_names;"
        "print(','.join(source_names()))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    discovered = [name for name in completed.stdout.strip().split(",") if name]
    assert discovered, "importing the pipeline must leave the registry populated"

    # Every concrete extractor module on disk must be represented. `community`
    # (the shared bank base class), `yomitan_bank` (the bank reader) and
    # `polarity_repair` (the shared headword-polarity fix-up) are infrastructure:
    # they are imported but register nothing, which is correct.
    expected = {
        path.stem
        for path in (REPO / "src/bugd/sources").glob("*.py")
        if path.stem
        not in {"__init__", "base", "registry", "community", "yomitan_bank", "polarity_repair"}
    }
    assert expected, "expected concrete source modules to be present"
    assert set(discovered) == expected, f"expected {sorted(expected)}, discovered {discovered}"


def test_source_discovery_is_deterministic_and_skips_infrastructure():
    from bugd.sources.registry import _NON_SOURCE_MODULES, load_source_modules

    imported = load_source_modules()
    assert imported == sorted(imported), "discovery order must be deterministic"
    assert not (set(imported) & _NON_SOURCE_MODULES)
    assert not any(name.startswith("_") for name in imported)
    # Idempotent: a second call must not double-register or raise.
    assert load_source_modules() == imported


def test_source_discovery_propagates_a_broken_module_instead_of_skipping_it(monkeypatch):
    """A source that cannot be imported is a build defect, not a smaller build.

    Swallowing the ImportError would silently ship a dictionary missing a whole
    source, which is exactly the failure mode the fail-closed policy forbids.
    """
    import bugd.sources.registry as registry

    def boom(name):
        raise ImportError(f"deliberately broken: {name}")

    monkeypatch.setattr(registry.importlib, "import_module", boom)
    with pytest.raises(ImportError):
        registry.load_source_modules()


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


# --------------------------------------------------------------------------
# row identity: source_id is NOT unique, so every row gets its own machine id
# --------------------------------------------------------------------------


def test_every_extracted_row_is_stamped_with_its_own_identity():
    """`ExtractResult` assigns `<source>:<ordinal>` in emission order."""
    points = [
        GrammarPoint(source="unit-fixture", source_id="dup", expression="あ"),
        GrammarPoint(source="unit-fixture", source_id="dup", expression="い"),
        GrammarPoint(source="unit-fixture", source_id="other", expression="う"),
    ]
    result = ExtractResult(source="unit-fixture", points=points)
    assert [p.row_uid for p in result.points] == [
        "unit-fixture:1",
        "unit-fixture:2",
        "unit-fixture:3",
    ]
    # The producer's own handle is untouched, and is still not unique.
    assert [p.source_id for p in result.points] == ["dup", "dup", "other"]


def test_two_rows_sharing_a_source_id_get_two_distinct_identities():
    """The defect this exists for: one edewakaru source_id names 22 rows.

    Asserted as a property of the whole batch rather than of two rows, so the
    test still bites if a future change makes identity depend on `source_id`.
    """
    points = [
        GrammarPoint(source="unit-fixture", source_id="あまり", expression="あまり", jlpt="N5"),
        GrammarPoint(source="unit-fixture", source_id="あまり", expression="あまり", jlpt="N2"),
    ]
    result = ExtractResult(source="unit-fixture", points=points)
    assert len({p.row_uid for p in result.points}) == len(result.points)


def test_a_duplicate_row_identity_fails_the_extraction_closed():
    """Renumbering silently would repoint claims that already cite the id."""
    points = [
        GrammarPoint(source="unit-fixture", source_id="a", expression="あ", row_uid="unit-fixture:1"),
        GrammarPoint(source="unit-fixture", source_id="b", expression="い", row_uid="unit-fixture:1"),
    ]
    with pytest.raises(DuplicateRowIdentity, match="unit-fixture:1"):
        ExtractResult(source="unit-fixture", points=points)


def test_a_preassigned_identity_survives_a_round_trip():
    """Re-wrapping already-stamped rows must not renumber them."""
    points = [
        GrammarPoint(source="unit-fixture", source_id="a", expression="あ", row_uid="unit-fixture:7"),
        GrammarPoint(source="unit-fixture", source_id="b", expression="い", row_uid="unit-fixture:9"),
    ]
    result = ExtractResult(source="unit-fixture", points=points)
    assert [p.row_uid for p in result.points] == ["unit-fixture:7", "unit-fixture:9"]


@pytest.mark.parametrize(
    "bad",
    [
        "unit-fixture:１",  # a fullwidth digit; int() would accept it
        "unit-fixture:1_0",  # an underscore; int() would accept it too
        "unit-fixture:0",  # ordinals are 1-based
        "unit-fixture:+1",  # a sign
        "unit-fixture:",  # no ordinal at all
        "other-source:1",  # a foreign source's identity
        "unit-fixture:1:2",
    ],
)
def test_a_malformed_row_identity_is_refused(bad):
    """Numeric syntax is checked before conversion, not after.

    Every rejected spelling here is one `int()` or a naive `split(':')` would
    wave through, which would let two spellings of one ordinal coexist and make
    the identity ambiguous again.
    """
    with pytest.raises(MalformedPayload, match="row_uid"):
        GrammarPoint(source="unit-fixture", source_id="a", expression="あ", row_uid=bad)


def test_row_identity_is_stable_across_repeated_extraction():
    """Same rows in, same identities out — a build input, not a nonce."""
    def build():
        return ExtractResult(
            source="unit-fixture",
            points=[
                GrammarPoint(source="unit-fixture", source_id="x", expression="あ"),
                GrammarPoint(source="unit-fixture", source_id="x", expression="い"),
            ],
        )

    assert [p.row_uid for p in build().points] == [p.row_uid for p in build().points]
# NINJAL 日本語文型データベース (Nihongo Bunkei Database) — XML source
# --------------------------------------------------------------------------


def test_ninjal_furigana_is_reduced_to_its_base_form():
    """The producer writes furigana inline as `〓漢字〔かな〕`.

    Rendered text must show the base form `漢字`, never `漢字(かな)` and never a
    stray `〓` marker. A lone marker with no reading is also removed.
    """
    from bugd.sources.ninjal_bunkei import strip_furigana

    assert strip_furigana("〓間〔あいだ〕") == "間"
    assert strip_furigana("〓新入〔しんにゅう〕〓社員〔しゃいん〕") == "新入社員"
    # Text with no furigana is returned unchanged.
    assert strip_furigana("～あげく") == "～あげく"
    # A bare marker never leaks even without a `〔…〕` reading.
    assert "〓" not in strip_furigana("〓orphan")


def test_ninjal_example_lifts_the_brace_highlight_and_strips_furigana():
    """The grammar point is wrapped in `｛…｝`; that substring is the highlight.

    The braces are removed from the surface sentence, the highlight carries the
    marked point (with its own furigana reduced), and it is never re-derived by
    searching the sentence for the headword.
    """
    from bugd.sources.ninjal_bunkei import example_from_text

    example = example_from_text(
        "〓時間〔じかん〕を〓延長〔えんちょう〕して〓話〔はな〕し〓合〔あ〕った｛あげく｝、"
        "〓会議〔かいぎ〕は〓終了〔しゅうりょう〕した。"
    )
    assert example is not None
    assert "｛" not in example.japanese and "｝" not in example.japanese
    assert "〓" not in example.japanese
    assert example.japanese.startswith("時間を延長して話し合ったあげく")
    assert example.highlight == ("あげく",)
    # A highlight that itself carries furigana is reduced to its base form.
    marked = example_from_text("さんざん〓悩〔なや〕んだ｛〓挙句〔あげく〕｝、買った。")
    assert marked is not None
    assert marked.highlight == ("挙句",)
    # An empty / whitespace-only example yields no Example rather than a blank one.
    assert example_from_text("   ") is None


def _ninjal_entry_xml(*, senses: str, pattern: str = "～テスト", reading: str = "～てすと") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Entry><SentencePattern>{pattern}</SentencePattern>"
        f"<Reading>{reading}</Reading><GeneralExplanation></GeneralExplanation>"
        f"{senses}</Entry>"
    ).encode("utf-8")


def test_ninjal_never_maps_its_teaching_level_onto_jlpt():
    """`<Level>` is NINJAL's difficulty axis (1–5), NOT a JLPT level.

    It must be recorded verbatim in provenance and the JLPT field must stay
    None — the same fail-closed "levels are read, never guessed" policy the
    community base enforces (DoJG's print-volume tag is handled identically).
    """
    from bugd.sources.ninjal_bunkei import NinjalBunkeiExtractor

    xml = _ninjal_entry_xml(
        senses=(
            "<Sense><SenceCategory>〓時〔とき〕</SenceCategory><Level>2</Level>"
            "<Usage>意味です。</Usage><UsageNotes>注意です。</UsageNotes>"
            "<Connection><ConnectionType>Vたテスト</ConnectionType>"
            "<ExampleSet><Example>〓例〔れい〕｛テスト｝です。</Example></ExampleSet>"
            "</Connection></Sense>"
        ),
    )
    extractor = NinjalBunkeiExtractor(pathlib.Path("."))
    point = extractor._parse_entry(xml, "～テスト.xml")
    assert point is not None
    assert point.jlpt is None
    assert point.provenance["ninjalLevels"] == ["2"]
    assert point.source == "ninjal_bunkei"
    assert point.expression == "～テスト"
    assert point.meaning == "意味です。"
    assert point.notes == "注意です。"
    assert point.structure == "Vたテスト"
    assert point.examples and point.examples[0].highlight == ("テスト",)


def test_ninjal_flattens_every_sense_without_collapsing_to_the_first():
    """A multi-sense pattern keeps all senses, each labelled by index."""
    from bugd.sources.ninjal_bunkei import NinjalBunkeiExtractor

    xml = _ninjal_entry_xml(
        senses=(
            "<Sense><SenceCategory>意味A</SenceCategory><Level>4</Level>"
            "<Usage>一つ目の意味。</Usage>"
            "<Connection><ConnectionType>形A</ConnectionType>"
            "<ExampleSet><Example>例一｛テスト｝。</Example></ExampleSet></Connection>"
            "</Sense>"
            "<Sense><SenceCategory>意味B</SenceCategory><Level>2</Level>"
            "<Usage>二つ目の意味。</Usage>"
            "<Connection><ConnectionType>形B</ConnectionType>"
            "<ExampleSet><Example>例二｛テスト｝。</Example></ExampleSet></Connection>"
            "</Sense>"
        ),
    )
    point = NinjalBunkeiExtractor(pathlib.Path("."))._parse_entry(xml, "多義.xml")
    assert point is not None
    assert point.meaning == "[1] 一つ目の意味。\n\n[2] 二つ目の意味。"
    assert point.provenance["ninjalLevels"] == ["4", "2"]
    assert point.structure == "形A\n形B"
    assert len(point.examples) == 2


def test_ninjal_extracts_every_locked_headword_from_the_real_archive():
    """End-to-end over the locked NINJAL distribution ZIP.

    Fails closed if the archive digest does not match its lock, reads only the
    locked bytes, and must yield one GrammarPoint per XML member with no leaked
    producer markup and no invented JLPT level.
    """
    from bugd.sources.ninjal_bunkei import NinjalBunkeiExtractor

    input_dir = REPO / "data/sources/ninjal_bunkei"
    if not (input_dir / "SOURCE.lock.json").is_file():  # pragma: no cover
        pytest.skip("ninjal_bunkei source data is not present in this checkout")

    result = NinjalBunkeiExtractor(input_dir).extract()
    assert result.source == "ninjal_bunkei"
    assert result.stats["members"] == len(result.points)
    assert result.stats["members"] > 700  # 800 headwords ship in this version
    assert result.stats["withJlpt"] == 0, "NINJAL publishes no JLPT level to read"
    for point in result.points:
        assert point.source == "ninjal_bunkei"
        assert point.jlpt is None
        assert "〓" not in (point.meaning or "")
        assert "｛" not in "".join(example.japanese for example in point.examples)


def test_ninjal_member_name_recovers_cp932_names_the_utf8_flag_missed():
    """21 of the archive's 800 members lack the UTF-8 name flag.

    `zipfile` decodes those Shift-JIS names as cp437, so without recovery the
    record identity for e.g. 召し上がります ships as the mojibake
    ``Åóé╡Åπé¬éΦé▄é╖``. `member_name` must round-trip the cp437 string back to
    bytes and decode CP932, and the extractor must use it for `source_id` and
    `provenance.sourceFile`.
    """
    import unicodedata
    import zipfile

    from bugd.sources.ninjal_bunkei import NinjalBunkeiExtractor, member_name

    input_dir = REPO / "data/sources/ninjal_bunkei"
    if not (input_dir / "SOURCE.lock.json").is_file():  # pragma: no cover
        pytest.skip("ninjal_bunkei source data is not present in this checkout")

    with zipfile.ZipFile(input_dir / "nihongo_bunkei_database20260126.zip") as archive:
        infos = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.endswith(".xml")
        ]
    unflagged = [info for info in infos if not info.flag_bits & 0x800]
    assert unflagged, "the distribution is known to ship unflagged CP932 names"
    for info in unflagged:
        assert member_name(info) != info.filename

    names = [member_name(info) for info in infos]
    assert len(set(names)) == len(names)

    def is_mojibake(text: str) -> bool:
        # cp437 mis-decoding yields Latin-1 supplement letters and box-drawing
        # characters; a real headword never contains either.
        return any(
            0x80 <= ord(ch) <= 0x2FFF and unicodedata.category(ch).startswith(("L", "S"))
            and not ("\u3000" <= ch)
            for ch in text
        ) or any("\u2500" <= ch <= "\u259F" for ch in text)

    result = NinjalBunkeiExtractor(input_dir).extract()
    bad = [
        point.source_id
        for point in result.points
        if is_mojibake(point.source_id) or is_mojibake(str(point.provenance["sourceFile"]))
    ]
    assert bad == [], f"mojibake identities leaked: {bad[:5]}"
