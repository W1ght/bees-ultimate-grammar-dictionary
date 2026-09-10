"""UGD-09 regressions: bank emission, index metadata, and gate integrity.

These cover the properties this card is responsible for, using the production
code path rather than hand-written fixtures:

* `build/banks/` exists and is byte-identical to the packaged ZIP members;
* `index.json` carries the metadata the card contract requires (title, revision,
  author, url, sequenced) plus per-source attribution;
* the schema gate still FAILS closed on malformed structured content — the point
  of the fast validator is speed, never leniency;
* the compact block is never emitted empty, so no card renders as a bare
  disclosure list.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import zipfile

import pytest

from bugd import (
    DICTIONARY_AUTHOR,
    DICTIONARY_DOWNLOAD_URL,
    DICTIONARY_INDEX_URL,
    DICTIONARY_TITLE,
    DICTIONARY_URL,
)
from bugd.banks import build_banks, build_index, build_tag_bank, build_term_entry
from bugd.merge import MergedEntry
from bugd.model import Example, GrammarPoint
from bugd.package import build_zip, package_members
from bugd.pipeline import BANKS_DIR_NAME, run_build, write_banks_dir
from bugd.styles import STYLES_CSS
from bugd.validate import validate_zip

SOURCE_LABELS = {"dojg": "DoJG 日本語文法辞典(全集)", "edewakaru": "絵でわかる日本語"}


def _point(**overrides) -> GrammarPoint:
    fields = {
        "source": "dojg",
        "source_id": "p1",
        "expression": "わけではない",
        "reading": "わけではない",
        "meaning": "it does not mean that",
        "structure": "〔普通形〕＋わけではない",
        "jlpt": "N3",
        "explanation": "<p>Denies a conclusion someone might draw.</p>",
        "examples": (
            Example(
                japanese="嫌いなわけではない。",
                english="It's not that I dislike it.",
                highlight=("わけではない",),
            ),
        ),
        "provenance": {"sourceLabel": SOURCE_LABELS["dojg"]},
    }
    fields.update(overrides)
    return GrammarPoint(**fields)


def _corpus_on_disk(tmp_path: pathlib.Path, entries: list[MergedEntry]) -> pathlib.Path:
    from bugd.pipeline import MERGED_CORPUS_NAME, entry_to_json

    merged_dir = tmp_path / "merged"
    merged_dir.mkdir(parents=True)
    (merged_dir / MERGED_CORPUS_NAME).write_text(
        json.dumps(
            {
                "sourceLabels": SOURCE_LABELS,
                "entries": [entry_to_json(entry) for entry in entries],
            }
        ),
        encoding="utf-8",
    )
    return merged_dir


# --------------------------------------------------------------- build/banks/


def test_build_emits_banks_dir_byte_identical_to_the_zip(tmp_path):
    entries = [MergedEntry(expression="わけではない", contributions=[_point()])]
    merged_dir = _corpus_on_disk(tmp_path, entries)
    build_dir = tmp_path / "build"

    result = run_build(
        merged_dir=merged_dir, build_dir=build_dir, dist_dir=None, require_entries=True
    )

    banks_dir = pathlib.Path(result["banksDir"])
    assert banks_dir == build_dir / BANKS_DIR_NAME
    assert banks_dir.is_dir()

    with zipfile.ZipFile(result["zipPath"]) as archive:
        names = sorted(archive.namelist())
        assert "term_bank_1.json" in names
        for name in names:
            on_disk = banks_dir / name
            assert on_disk.is_file(), f"{name} missing from build/banks/"
            assert (
                hashlib.sha256(on_disk.read_bytes()).hexdigest()
                == hashlib.sha256(archive.read(name)).hexdigest()
            ), f"{name} differs between build/banks/ and the ZIP"

    on_disk_names = sorted(str(p.relative_to(banks_dir)) for p in banks_dir.rglob("*") if p.is_file())
    assert on_disk_names == names, "build/banks/ must mirror the ZIP exactly"


def test_banks_dir_is_rebuilt_so_a_stale_bank_cannot_linger(tmp_path):
    build_dir = tmp_path / "build"
    stale = build_dir / BANKS_DIR_NAME / "term_bank_9.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")

    write_banks_dir({"index.json": "{}"}, build_dir=build_dir)

    assert not stale.exists(), "a bank dropped from the corpus must not survive a rebuild"
    assert (build_dir / BANKS_DIR_NAME / "index.json").is_file()


# ----------------------------------------------------------------- index.json


def test_index_carries_the_required_card_contract_metadata():
    index = build_index("2026.09.08", source_labels=SOURCE_LABELS)

    assert index["title"] == DICTIONARY_TITLE
    assert index["revision"] == "2026.09.08"
    assert index["author"] == DICTIONARY_AUTHOR
    assert index["url"] == DICTIONARY_URL
    assert index["sequenced"] is True
    assert index["format"] == 3
    # Per-source attribution travels with the archive, not only inside cards.
    for label in SOURCE_LABELS.values():
        assert label in index["attribution"]
    # Self-updating by default: the archive says where it came from, which is what
    # lets a downstream installer verify it and check for a newer revision.
    assert index["isUpdatable"] is True
    assert index["indexUrl"] == DICTIONARY_INDEX_URL
    assert index["downloadUrl"] == DICTIONARY_DOWNLOAD_URL


def test_index_can_be_built_local_only():
    """Both URLs off together is still a valid archive: it just advertises no updates."""
    index = build_index("2026.09.08", index_url=None, download_url=None)
    assert "isUpdatable" not in index
    assert "indexUrl" not in index
    assert "downloadUrl" not in index


def test_index_refuses_a_half_configured_updater():
    """Yomitan makes `isUpdatable` depend on BOTH URLs, so one alone is invalid."""
    with pytest.raises(Exception):
        build_index("2026.09.08", index_url=None)
    with pytest.raises(Exception):
        build_index("2026.09.08", download_url=None)


# ------------------------------------------------------------- card integrity


def test_a_card_never_renders_as_a_bare_sources_disclosure():
    """A card whose sources say nothing must still say something truthful.

    A card whose entire visible content is a `Sources` disclosure reads as a
    broken entry. The fallback states only what the source actually asserts —
    that it listed the point — and never invents a gloss, a reading, or a level.
    """
    bare = _point(
        meaning=None, structure=None, jlpt=None, explanation=None, examples=(),
        provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]},
    )
    entry = MergedEntry(expression="あいにく", contributions=[bare])

    card = build_term_entry(entry, 1)[5][0]["content"]

    def texts(node, out):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, list):
            for item in node:
                texts(item, out)
        elif isinstance(node, dict):
            texts(node.get("content"), out)
        return out

    def roles(node, found):
        if isinstance(node, list):
            for item in node:
                roles(item, found)
        elif isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                found.update(data.keys())
            for value in node.values():
                roles(value, found)
        return found

    present = roles(card, set())
    assert {"crossref", "listedOnly"} & present, (
        "an entry with no substance must still render a truthful statement, "
        f"got roles {sorted(present)}"
    )

    rendered = " ".join(texts(card, []))
    assert SOURCE_LABELS["edewakaru"] in rendered
    # Nothing may be invented to fill the space.
    for invented in ("N5", "N4", "N3", "N2", "N1"):
        assert invented not in rendered


def test_no_emitted_card_in_the_real_corpus_is_bare():
    """Corpus-wide gate: run the real merged corpus if it has been built.

    A single fixture cannot prove the fallback chain covers every real shape, so
    this scans every emitted card when the corpus is present and skips otherwise
    (a fresh clone has no `data/merged/`).
    """
    from bugd.pipeline import MERGED_CORPUS_NAME, entry_from_json

    corpus_path = pathlib.Path("data/merged") / MERGED_CORPUS_NAME
    if not corpus_path.is_file():
        pytest.skip("no merged corpus on disk")

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    entries = [entry_from_json(item) for item in corpus["entries"]]

    def roles(node, found):
        if isinstance(node, list):
            for item in node:
                roles(item, found)
        elif isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                found.update(data.keys())
            for value in node.values():
                roles(value, found)
        return found

    bare = []
    for position, entry in enumerate(entries, start=1):
        card = build_term_entry(entry, position)[5][0]["content"]
        compact_empty = not card["content"][0].get("content")
        present = roles(card, set())
        substantive = bool(
            {"crossref", "listedOnly", "sourceBlock", "prose", "examples", "patterns"} & present
        )
        if compact_empty and not substantive:
            bare.append(entry.expression)

    assert not bare, f"{len(bare)} cards would render as a bare Sources disclosure: {bare[:10]}"


def test_term_entries_are_one_canonical_structured_surface():
    entry = MergedEntry(expression="わけではない", contributions=[_point()])
    expression, reading, deftags, deinflectors, score, glossary, sequence, termtags = (
        build_term_entry(entry, 7)
    )

    assert expression == "わけではない"
    # reading == expression is a redundant furigana pair in Yomitan.
    assert reading == ""
    assert sequence == 7
    assert len(glossary) == 1, "one card per grammar point, not competing glossaries"
    assert glossary[0]["type"] == "structured-content"


# -------------------------------------------------------------- gate integrity


def _zip_with_bank(tmp_path: pathlib.Path, bank: list, name: str = "malformed.zip") -> pathlib.Path:
    members = package_members(
        index=build_index("2026.09.08", source_labels=SOURCE_LABELS),
        banks={"term_bank_1.json": bank},
        tag_bank=build_tag_bank(SOURCE_LABELS),
        styles_css=STYLES_CSS,
    )
    path = tmp_path / name
    path.write_bytes(build_zip(members))
    return path


def test_gate_still_rejects_a_tag_outside_yomitans_allowlist(tmp_path):
    """The fast validator must be no more permissive than the slow one.

    `p` is NOT in Yomitan's structured-content allowlist even though it is
    obvious HTML, so it is the sharpest available probe that the accelerated gate
    still enforces the real pinned schema.
    """
    entry = build_term_entry(
        MergedEntry(expression="わけではない", contributions=[_point()]), 1
    )
    entry[5][0]["content"]["content"].append({"tag": "p", "content": "not allowed"})

    failures = validate_zip(_zip_with_bank(tmp_path, [entry]), require_entries=True)

    assert failures, "a nested `p` tag must fail the pinned term-bank schema"
    assert any("term_bank_1.json" in failure for failure in failures)


@pytest.mark.parametrize(
    "bank, reason",
    [
        ([["surface", "", "", "", 0, ["gloss"], "not-an-int", ""]], "sequence must be integer"),
        ([["surface", ""]], "entry is too short"),
        ([["surface", "", "", "", 0, "plain-not-array", 1, ""]], "glossary must be an array"),
        ({"nope": True}, "bank must be an array"),
    ],
)
def test_gate_rejects_structurally_invalid_banks(tmp_path, bank, reason):
    failures = validate_zip(_zip_with_bank(tmp_path, bank), require_entries=True)
    assert failures, f"expected the gate to reject: {reason}"


def test_banks_shard_contiguously_with_positive_sequences():
    entries = [
        MergedEntry(expression=f"点{index}", contributions=[_point(source_id=f"p{index}")])
        for index in range(5)
    ]
    banks = build_banks(entries)

    assert sorted(banks) == ["term_bank_1.json"]
    sequences = [entry[6] for entry in banks["term_bank_1.json"]]
    assert sequences == [1, 2, 3, 4, 5]


def test_prose_keeps_the_sources_paragraph_breaks():
    """Sources publish prose with hard line breaks and blank-line paragraphs.

    Measured in real Yomitan 26.8.24.0: collapsing every newline to a space
    rendered a 426-character explanation as one unreadable run-on block, while
    the source had 53 newlines. 2,318 of the corpus's 9,400 prose fields carry a
    blank line, so a paragraph break must survive as `\\n` for the card's
    `white-space: pre-line` to break on, and a soft-wrap newline must not.
    """
    from bugd.richtext import html_to_content, html_to_text

    assert html_to_content("wrapped line\nsame paragraph") == "wrapped line same paragraph"
    assert html_to_content("para one\n\npara two") == "para one\npara two"
    # A run of blank lines is one break, not several.
    assert html_to_content("a\n\n\n\nb") == "a\nb"
    # A blank line made of ideographic space is still a paragraph break.
    assert html_to_content("a\n\u3000\nb") == "a\nb"
    # Ideographic space inside a line is real content in Japanese prose.
    assert html_to_content("a\u3000\u3000b") == "a\u3000\u3000b"
    # Headwords and labels must stay on one line.
    assert html_to_text("para one\n\npara two") == "para one para two"
    assert "\n" not in html_to_text("a\n\nb\n\nc")


def test_prose_keeps_the_break_before_a_list_enumerator():
    """A newline before a list item is semantic, not a soft wrap.

    Round 6 of the UGD-14 beauty gate scored くらい 6/10 with a must-fix: the
    numbered explanation rendered as one run-on paragraph reading
    `…使う。 ２）話者の意志を… ３）意味・用法は…`. The source was intact (9
    newlines); `_paragraphize` collapsed the single newlines to spaces because
    only blank lines counted as breaks. Measured over the corpus: 2,107 such
    newlines across 885 records in 5 sources.

    The rule is deliberately narrow -- it fires only when the following line
    OPENS with an enumerator, so an enumerator used as an inline reference
    (`同時動作（N４）`, `例文（７）（８）`) is untouched.
    """
    from bugd.richtext import html_to_content

    # Fullwidth numeric enumerators (donna_toki, the reported defect).
    assert html_to_content("使う。\n２）話者の意志を表さない") == "使う。\n２）話者の意志を表さない"
    # Circled digits (edewakaru, nihongo_net).
    assert html_to_content("〜のようだ\n②〜しやすい") == "〜のようだ\n②〜しやすい"
    # ASCII parenthesised enumerators (dojg structure tables).
    assert html_to_content("expensive.\n(2) Adjective") == "expensive.\n(2) Adjective"
    # An enumerator may be indented by ideographic space.
    assert html_to_content("a\n\u3000１）b") == "a\n１）b"

    # A genuine soft wrap still collapses. Latin prose keeps its word-boundary
    # space; Japanese joins with nothing, because Japanese has no inter-word space
    # (see `test_a_japanese_soft_wrap_joins_without_a_space`).
    assert html_to_content("wrapped line\nsame paragraph") == "wrapped line same paragraph"
    # An enumerator MID-sentence is an inline reference, not a list item, so the
    # preceding soft-wrap newline must still collapse -- and between two Japanese
    # characters it collapses to nothing, which is how the producer's own page
    # reads: `同時動作（N４）のほかに`.
    assert html_to_content("同時動作\n（N４）のほかに") == "同時動作（N４）のほかに"
    assert html_to_content("は\n例文（７）（８）") == "は例文（７）（８）"
    # A digit that is not an enumerator must not trigger a break.
    assert html_to_content("about\n2 volumes") == "about 2 volumes"


def test_prose_keeps_the_break_between_wave_dash_pattern_list_items():
    """A `〜`-notation cross-reference list is one item per line, not a run-on.

    UGD-08c filed the 「もの」シリーズ list twice on たい (findings 8, 11): the source
    ships one pattern per line, each opening with the corpus's WAVE DASH, and
    `_paragraphize` soft-joined them into `〜たものだ〜ないものだろうか〜ないものは〜ない…`.
    This is the `〜`-list sibling of `_LIST_BREAK`'s numbered lists. Measured over
    the corpus: 750 runs of two or more such lines / 3,588 items / 665 fields.

    The rule fires only when BOTH adjacent lines are wave-dash pattern notation, so
    a single `〜X` reference the producer wrapped after a prose sentence is spared.
    """
    from bugd.richtext import html_to_content

    # The reported もの-series list: every adjacent pattern-line pair keeps its break.
    assert html_to_content(
        "〜たものだ\n〜ないものだろうか\n〜もの・〜んだもの\n〜ものか"
    ) == "〜たものだ\n〜ないものだろうか\n〜もの・〜んだもの\n〜ものか"
    # The fullwidth tilde spelling of the placeholder is the same list shape.
    assert html_to_content("～ものなら\n～ものの") == "～ものなら\n～ものの"

    # A single reference the producer wrapped AFTER a prose sentence still
    # collapses: the first line is not a pattern-list line, so the both-sides guard
    # spares it and Japanese joins with nothing.
    assert html_to_content("この文型は\n〜くらいと似ています") == "この文型は〜くらいと似ています"
    # Inline references inside one sentence are one line and untouched.
    assert (
        html_to_content("ほとんどの文型は「〜ものなら」「〜もので」のように決まっています。")
        == "ほとんどの文型は「〜ものなら」「〜もので」のように決まっています。"
    )
    # A wave-opening line that ends in sentence punctuation is NOT a pattern-list
    # item (the `！` disqualifies it), so the pattern-list rule does not fire; the
    # break is decided by the ordinary sentence-end rule, which keeps it.
    assert html_to_content("〜だこと！\nと言います") == "〜だこと！\nと言います"
    # Two wave-opening prose sentences (both end in 。) are not pattern-list items,
    # so the pattern-list rule does not glue-or-split them; the sentence-end rule
    # keeps each on its own line.
    assert html_to_content("〜ごとし。\n〜ごとく。") == "〜ごとし。\n〜ごとく。"


def test_prose_keeps_the_break_between_stem_sharing_parallel_examples():
    """Consecutive example sentences that restart a shared stem stay separate.

    edewakaru writes some ［例］ runs as parallel example sentences varying one slot
    of a shared opening, each split further into node-lines so the next example's
    first node is exactly the stem the previous one opened with. Neither sentence
    ends in punctuation, so `_paragraphize` Japanese-joined them into one run
    (`…計画を実行した彼は法律に反する計画を実行した`) -- the sole residual run-on the UGD-08c
    gate still flagged on に反して after the first three fixes.

    A soft wrap whose NEXT line is a >=3-char Japanese leading prefix of the
    CURRENT (fully-joined) line is a fresh parallel example, so the break survives.
    """
    from bugd.richtext import html_to_content

    # The reported に反して parallel set: each variant restarts `彼は法律`.
    assert html_to_content(
        "彼は法律\nに反して、計画を実行した\n彼は法律\nに反する計画を実行した"
    ) == "彼は法律に反して、計画を実行した\n彼は法律に反する計画を実行した"

    # An ordinary single sentence wrapped mid-way still joins: the continuation is
    # NOT a leading prefix of the sentence so far.
    assert html_to_content("友達を待っている\n間、音楽を聞いた") == "友達を待っている間、音楽を聞いた"
    # A two-character shared opening (a bare particle `私は`) is below the stem
    # floor, so two unrelated sentences are not split apart.
    assert html_to_content("私は学生\nですが働いています") == "私は学生ですが働いています"


def test_prose_paragraph_sentinel_cannot_be_smuggled_in_by_a_source():
    """The break sentinel must not be forgeable from source bytes."""
    from bugd.richtext import html_to_content

    assert html_to_content("a\x00b") == "ab"
    # `\v` is matched by the inline-whitespace pattern, so it must NOT be the
    # sentinel: using it silently ate every paragraph break.
    assert html_to_content("a\x0bb") == "a b"


def test_multi_paragraph_prose_becomes_spaced_sibling_blocks():
    """`pre-line` breaks paragraphs but cannot space them.

    A 400-character explanation carrying eight preserved breaks still read as one
    dense block in the real host because consecutive lines merely touched. Each
    paragraph becomes its own div so the stylesheet's `div + div` rule spaces it.
    """
    from bugd.banks import _paragraphs

    # A single paragraph stays a plain string: nothing is wrapped needlessly.
    assert _paragraphs("only one") == "only one"
    assert _paragraphs("p1\np2\np3") == [
        {"tag": "div", "content": "p1"},
        {"tag": "div", "content": "p2"},
        {"tag": "div", "content": "p3"},
    ]
    # Blank paragraphs are dropped rather than emitted as empty blocks.
    assert _paragraphs("p1\n\np2") == [
        {"tag": "div", "content": "p1"},
        {"tag": "div", "content": "p2"},
    ]
    # Existing nodes pass through untouched.
    assert _paragraphs({"tag": "span", "content": "x"}) == {"tag": "span", "content": "x"}


def test_multi_paragraph_explanation_reaches_the_built_card():
    """The split must be wired into the real term entry, not just available."""
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="間",
        meaning="during",
        explanation="first paragraph.\n\nsecond paragraph.",
    )
    row = build_term_entry(MergedEntry(expression="間", contributions=[point]), 1)
    blob = json.dumps(row, ensure_ascii=False)
    assert "first paragraph." in blob
    assert "second paragraph." in blob
    # Two sibling divs, not one run-on string.
    assert "first paragraph.\\nsecond paragraph." not in blob


def test_a_wide_space_dialogue_separator_becomes_a_line_break():
    """DoJG separates two-speaker turns with a double EM SPACE.

    Rendered inline in the real host it looked like broken justification -- a
    large gap mid-sentence. 31 examples use it; the turn boundary is semantic, so
    it becomes a `br`.
    """
    from bugd.banks import _split_dialogue_turns

    assert _split_dialogue_turns("A:\u3053\u308c\uff1f\u2003\u2003B:\u306f\u3044") == [
        "A:\u3053\u308c\uff1f",
        {"tag": "br"},
        "B:\u306f\u3044",
    ]
    # A single wide space is ordinary Japanese spacing, not a turn boundary.
    assert _split_dialogue_turns("\u3042\u3044\u3060\u3000\u306e") == "\u3042\u3044\u3060\u3000\u306e"
    # Highlight nodes must survive untouched.
    node = {"tag": "span", "content": "x"}
    assert _split_dialogue_turns(["A\u2003\u2003B", node]) == ["A", {"tag": "br"}, "B", node]


def test_a_speaker_label_starts_a_new_dialogue_line():
    """A second speaker label is a turn boundary even with no wide space.

    Round 7 of the beauty gate filed a must-fix on くらい: `A：…B：…` rendered as
    one run-on line. The existing wide-space rule only caught DoJG's double EM
    SPACE; measured over the corpus, 806 example fields across 352 records in 3
    sources (edewakaru 558, dojg 195, donna_toki 53) glue turns together with the
    label alone.
    """
    from bugd.banks import _split_dialogue_turns

    # Fullwidth colon, no separating space (edewakaru / donna_toki).
    assert _split_dialogue_turns("Ａ：これ？Ｂ：はい") == [
        "Ａ：これ？", {"tag": "br"}, "Ｂ：はい",
    ]
    assert _split_dialogue_turns("A：これ？B：はい") == [
        "A：これ？", {"tag": "br"}, "B：はい",
    ]
    # Halfwidth colon with the source's two wide spaces (DoJG) still yields ONE
    # break, not two.
    assert _split_dialogue_turns("A:これ？\u2003\u2003B:はい") == [
        "A:これ？", {"tag": "br"}, "B:はい",
    ]
    # A third turn breaks too.
    assert _split_dialogue_turns("A：あ。B：い。A：う。") == [
        "A：あ。", {"tag": "br"}, "B：い。", {"tag": "br"}, "A：う。",
    ]
    # The FIRST label must not produce a leading break.
    assert _split_dialogue_turns("A：ひとり") == "A：ひとり"

    # Must NOT fire on ordinary prose that happens to contain a capital + colon.
    assert _split_dialogue_turns("see B：") == "see B："
    assert _split_dialogue_turns("ratio A:B is fixed") == "ratio A:B is fixed"
    # A letter that is not a speaker label is left alone.
    assert _split_dialogue_turns("だからC：ではない") == "だからC：ではない"


def test_a_chinese_gloss_never_becomes_the_visible_meaning_or_a_sense_heading():
    """毎日のんびり日本語教師 publishes a Chinese translation column.

    Round 8 of the beauty gate filed a must-fix on くらい: two section headings
    read `…最…` and `…左右 大概… …多 与…相同 和…一样`, which are Chinese gloss
    lists, not garbled Japanese. Measured in the packaged archive before the fix:
    487 of 1,990 compact meaning lines and 124 of 718 sense labels, all of them
    additionally declared `lang="ja"` because Han sits inside the Japanese ranges.

    The source's OWN Japanese line is used instead when it has one; nothing is
    translated or invented.
    """
    from bugd.banks import _is_chinese_gloss, _readable_meaning

    # The signal is Han + a Chinese mark in a kana-free, Latin-free line: `…` is
    # the Chinese slot placeholder (Japanese uses `〜`) and `，` its enumeration
    # comma (Japanese uses `、`).
    assert _is_chinese_gloss("太…")
    assert _is_chinese_gloss("…左右 大概… …多 与…相同 和…一样")
    assert _is_chinese_gloss("取决于…")
    assert _is_chinese_gloss("正因为有了Ａ，才有Ｂ的存在")
    # Japanese always carries kana in this corpus, even when Han-heavy.
    assert not _is_chinese_gloss("～によっては")
    assert not _is_chinese_gloss("名詞＋あっての＋名詞Ｂ")
    # An all-shared-Han line with NO Chinese mark stays Japanese. Script alone
    # cannot separate `程度`/`以前`/`五段動詞` from a short Chinese gloss, and
    # under-claiming is safer than mislabelling Japanese as Chinese.
    assert not _is_chinese_gloss("程度")
    assert not _is_chinese_gloss("以前")
    assert not _is_chinese_gloss("五段動詞")
    # English is not Chinese.
    assert not _is_chinese_gloss("difficult to do")
    assert not _is_chinese_gloss("")
    # A dialogue turn is not a gloss, even though `母` is Han and `…` is present.
    assert not _is_chinese_gloss("母：…")

    # The source's own Japanese line is preferred over its Chinese lines.
    assert _readable_meaning("取决于…\n根据…\n～によっては\n～次第で（は）") == "～によっては"
    # An all-Chinese field yields nothing, so the caller falls back to another
    # field rather than printing an unreadable heading.
    assert _readable_meaning("总之…\n无论怎样…\n不管怎样…") == ""
    # An ordinary field is returned unchanged.
    assert _readable_meaning("during; while") == "during; while"
    assert _readable_meaning(None) == ""


def test_a_chinese_only_meaning_falls_back_to_the_source_pattern():
    """1,057 of the affected records carry a `structure` formula instead.

    So the sense keeps a real, source-authored heading rather than an empty one
    or an invented gloss.
    """
    points = [
        GrammarPoint(
            source="nihongo_no_sensei",
            source_id="1",
            expression="いずれにしても",
            meaning="总之…\n无论怎样…",
            structure="いずれにしても＋文",
            explanation="一つ。",
        ),
        GrammarPoint(
            source="nihongo_no_sensei",
            source_id="2",
            expression="いずれにしても",
            meaning="反正…",
            structure="いずれにしろ＋文",
            explanation="二つ。",
        ),
    ]
    row = build_term_entry(
        MergedEntry(expression="いずれにしても", contributions=points), 1
    )
    blob = json.dumps(row, ensure_ascii=False)
    # No Chinese gloss reaches the card as a heading or the primary line.
    for chinese in ("总之", "无论怎样", "反正"):
        assert chinese not in blob, f"{chinese!r} still rendered"
    # The source's own pattern is what labels the sense.
    assert "いずれにしても＋文" in blob
    # And the card is NOT left bare: its explanations still render.
    assert "一つ。" in blob
    assert "二つ。" in blob


def test_a_dialogue_written_inside_a_prose_field_also_breaks():
    """Two sources put a two-speaker exchange in an explanation, not an example.

    The packaged v10 archive still carried one run-on after the example-side fix
    landed, because the splitter only ran on examples: donna_toki's `たらいい`
    explanation and nihongo_net's `meaning` write the exchange as prose.
    """
    from bugd.banks import _split_dialogue_prose

    assert _split_dialogue_prose(
        "A：あした、晴れたらいいな。B：そうですね、いい天気だったらいいですね。"
    ) == [
        "A：あした、晴れたらいいな。",
        {"tag": "br"},
        "B：そうですね、いい天気だったらいいですね。",
    ]

    # DoJG writes its construction table as text, where `A:` is a COLUMN HEADER,
    # not a speaker. A line carrying pipe delimiters must never be split, or a
    # table row is broken mid-notation.
    assert _split_dialogue_prose("(i) A: | Sentence1 | |") == "(i) A: | Sentence1 | |"
    assert _split_dialogue_prose("(ii) A: Sentence | | |") == "(ii) A: Sentence | | |"

    # Ordinary prose is untouched.
    assert _split_dialogue_prose("この文型は丁寧です。") == "この文型は丁寧です。"


def test_a_prose_dialogue_reaches_the_built_card_as_separate_lines():
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="たらいい",
        meaning="hope",
        explanation="A：あした、晴れたらいいな。B：そうですね。",
    )
    row = build_term_entry(MergedEntry(expression="たらいい", contributions=[point]), 1)
    blob = json.dumps(row, ensure_ascii=False)
    assert '"br"' in blob
    # The two turns must not remain one string.
    assert "いいな。B：" not in blob


def test_a_kanji_role_speaker_label_also_starts_a_new_line():
    """Most of the corpus's dialogue uses ROLE nouns, not `A:`/`B:`.

    Round 7 re-filed the run-on must-fix after the Latin-only rule shipped,
    because the actual flagged example was `夫：…妻：…`. Measured over the corpus,
    role labels outnumber Latin ones: 娘 45, 母 37, 夫 8, 妻 8, 弟 7, 彼氏 7,
    学生 6, 店員 6, and 25 more.
    """
    from bugd.banks import _split_dialogue_turns

    assert _split_dialogue_turns(
        "夫：ちょっと厳しすぎじゃないか？妻：この子にはこれくらいしなきゃだめなのよ！"
    ) == [
        "夫：ちょっと厳しすぎじゃないか？",
        {"tag": "br"},
        "妻：この子にはこれくらいしなきゃだめなのよ！",
    ]
    # A multi-character role, and a third turn returning to the first speaker.
    assert _split_dialogue_turns(
        "母親：もう勉強は終わったの。娘：やってらんないわよ。母親：しょうがない子ねえ。"
    ) == [
        "母親：もう勉強は終わったの。",
        {"tag": "br"},
        "娘：やってらんないわよ。",
        {"tag": "br"},
        "母親：しょうがない子ねえ。",
    ]
    # An indexed role (several customers in one scene).
    assert _split_dialogue_turns("店員：何になさいますか？客A：ハンバーガーにします") == [
        "店員：何になさいますか？", {"tag": "br"}, "客A：ハンバーガーにします",
    ]

    # Inside a recognised TRANSCRIPT (the text opens with a speaker label), a
    # later label is a turn change even with no punctuation before it -- the
    # producer's casual dialogue often ends a turn on a bare sentence-final
    # particle. `夫：…すまん妻：…` is such a case: `すまん` closes the husband's turn.
    out = _split_dialogue_turns(
        "妻：あの子が泣くに決まってるでしょ！夫：…すまん妻：もっとやさしい言い方が"
    )
    assert out == [
        "妻：あの子が泣くに決まってるでしょ！",
        {"tag": "br"},
        "夫：…すまん",
        {"tag": "br"},
        "妻：もっとやさしい言い方が",
    ]

    # But the split must never land INSIDE a label: an indexed role keeps its
    # role attached, rather than orphaning `客` onto the previous line.
    assert _split_dialogue_turns(
        "店員：何になさいますか？客A：ハンバーガーにします客B：ギョーザにします"
    ) == [
        "店員：何になさいますか？",
        {"tag": "br"},
        "客A：ハンバーガーにします",
        {"tag": "br"},
        "客B：ギョーザにします",
    ]

    # A role noun in ordinary prose (no preceding sentence end, and the text does
    # NOT open with a speaker label) is untouched.
    assert _split_dialogue_turns("うちの母：とても優しい") == "うちの母：とても優しい"


def test_a_turn_ending_in_a_wave_dash_still_breaks():
    """Casual dialogue lengthens the last vowel instead of closing with 。/！.

    Round 8 filed `娘：お母さん、りんごをむいて〜母：それくらい自分でやって…` and
    `彼女：こんなもの…食べて〜 彼氏：わぁ〜おいしそう！` as run-ons. Measured over the
    corpus, 46 turn boundaries are marked this way, all in edewakaru.
    """
    from bugd.banks import _split_dialogue_turns

    assert _split_dialogue_turns("娘：お母さん、りんごをむいて〜母：それくらい自分で") == [
        "娘：お母さん、りんごをむいて〜", {"tag": "br"}, "母：それくらい自分で",
    ]
    # Fullwidth tilde form.
    assert _split_dialogue_turns("娘：ただいま～母：おかえり") == [
        "娘：ただいま～", {"tag": "br"}, "母：おかえり",
    ]

    # `〜` is ALSO this corpus's grammar-pattern placeholder, so it must only act
    # as a turn boundary in the same position as any other turn-final mark:
    # immediately before a speaker label bearing a colon.
    assert _split_dialogue_turns("〜くらい〜はない") == "〜くらい〜はない"
    assert _split_dialogue_turns("〜ほど〜はない") == "〜ほど〜はない"
    assert _split_dialogue_turns("Ａくらい〜だ") == "Ａくらい〜だ"


def test_a_transcript_breaks_even_with_no_punctuation_between_turns():
    """A turn can end on a bare sentence-final particle with no punctuation.

    Round 8 filed `A：今日はすごく寒いねB：うん。雪が降るかもね` as a run-on. Measured
    over the corpus, 35 distinct characters precede a second speaker label and the
    long tail is exactly this: `よ` 60, `ね` 58, `い` 47, `の` 26, `わ` 12. No
    punctuation rule can reach them, and anchoring on "any kana" would fire in
    ordinary prose.

    So the LINE decides: text that OPENS with a speaker label is a transcript, and
    inside a transcript a later label is a turn change.
    """
    from bugd.banks import _split_dialogue_turns

    assert _split_dialogue_turns("A：今日はすごく寒いねB：うん。雪が降るかもね") == [
        "A：今日はすごく寒いね", {"tag": "br"}, "B：うん。雪が降るかもね",
    ]
    assert _split_dialogue_turns(
        "A：山田くんは、今日のパーティーにくるかなB：最近忙しそうだから"
    ) == [
        "A：山田くんは、今日のパーティーにくるかな",
        {"tag": "br"},
        "B：最近忙しそうだから",
    ]

    # Crucially, the SAME sentence-final particle in prose that does NOT open with
    # a speaker label is left alone -- that is what keeps the rule from firing on
    # explanations.
    assert (_split_dialogue_turns("これは丁寧な言い方だねB：という形もある")
            == "これは丁寧な言い方だねB：という形もある")

    # A transcript's own opening label never produces a leading break.
    out = _split_dialogue_turns("A：ひとりだけ")
    assert out == "A：ひとりだけ"

    # Highlight nodes fragment the string, so the transcript test reads the JOINED
    # text: the opening label and a later one can sit in different fragments.
    hl = {"tag": "span", "data": {"hl": ""}, "content": "くらい"}
    assert _split_dialogue_turns(["A：これ", hl, "ですねB：はい"]) == [
        "A：これ", hl, "ですね", {"tag": "br"}, "B：はい",
    ]

    # And the next speaker's label can be the FIRST thing in a post-highlight
    # fragment, where a "later label" rule sees nothing before it. 22 examples
    # shipped as run-ons for exactly this reason.
    teku = {"tag": "span", "data": {"hl": ""}, "content": "てください"}
    assert _split_dialogue_turns(
        ["A：すみませんが、駅までの行き方を教え", teku, "B：いいですよ"]
    ) == [
        "A：すみませんが、駅までの行き方を教え", teku, {"tag": "br"}, "B：いいですよ",
    ]


def test_a_dialogue_turn_on_its_own_source_line_keeps_its_break():
    """These sources publish an exchange with one hard break per turn.

    The soft-wrap rule glued them together, so the card showed
    `B：３００円しか当たらなかったよ A：当たっただけましだよ！` -- filed by the UGD-14
    round-8 visual gate as a run-on. Same treatment as a numbered list item: the
    break is semantic, so it survives.
    """
    from bugd.richtext import _paragraphize

    assert _paragraphize(
        "B：３００円しか当たらなかったよ\nA：当たっただけましだよ！"
    ) == "B：３００円しか当たらなかったよ\nA：当たっただけましだよ！"
    assert _paragraphize(
        "母：疲れてたみたいで、聞きそびれちゃったの\n娘：じゃあ、今日聞いてみてね"
    ) == "母：疲れてたみたいで、聞きそびれちゃったの\n娘：じゃあ、今日聞いてみてね"

    # Anchored on the START of the following line, so a role noun or letter
    # occurring mid-sentence still soft-wraps into one paragraph -- and a wrap
    # between two Japanese characters joins with NOTHING, because Japanese has no
    # inter-word space (see `test_a_japanese_soft_wrap_joins_without_a_space`).
    assert _paragraphize("うちの母は\nとても優しい") == "うちの母はとても優しい"
    assert _paragraphize("この文型は\n丁寧です") == "この文型は丁寧です"


def test_a_japanese_soft_wrap_joins_without_a_space():
    """A soft wrap inside a Japanese sentence must join with nothing.

    `_SOFT_BREAK` substituted a LATIN space for every producer soft wrap, so the
    card rendered `私たち夫婦の 間 に秘密なんてありません` and even a space before a `、`
    in `友達を待っている 間、音楽をきいていた`. The UGD-14 round-8 visual gate filed both
    as "unnatural extra spaces ... reads as broken text rendering". The producer
    ships no stray spaces: edewakaru puts the highlighted grammar point on its own
    line, so one sentence arrives as three lines.

    Measured over the corpus: 17,839 wraps join with nothing, 13,537 stay breaks,
    92 join with a space, and zero glues fuse two Latin alphanumerics.
    """
    from bugd.richtext import _paragraphize

    assert (_paragraphize("私たち夫婦の\n間\nに秘密なんてありません")
            == "私たち夫婦の間に秘密なんてありません")
    assert (_paragraphize("友達を待っている\n間、音楽をきいていた")
            == "友達を待っている間、音楽をきいていた")

    # A Latin word boundary still needs its space, or the gloss prose fuses.
    assert (_paragraphize("to the extent\nthat it happens")
            == "to the extent that it happens")

    # A following structural line is a real line, so joining must not swallow it:
    # that would replace a spacing defect with a worse run-on.
    assert (_paragraphize("に秘密なんてありません\n【〜と〜との関係の中のこと】")
            == "に秘密なんてありません\n【〜と〜との関係の中のこと】")
    assert (_paragraphize("間、音楽をきいていた\n→友達が来るまで")
            == "間、音楽をきいていた\n→友達が来るまで")
    # A preceding sentence end is also a real boundary.
    assert (_paragraphize("これは丁寧です。\n次の文型を見ましょう")
            == "これは丁寧です。\n次の文型を見ましょう")
    # A table row keeps its `|` rows apart.
    assert (_paragraphize("| 四冊くらい | About four |\n| 百人くらい | About a hundred |")
            == "| 四冊くらい | About four |\n| 百人くらい | About a hundred |")


def test_a_bare_carriage_return_inside_a_word_is_not_a_space():
    """donna_toki writes `社\\r長` -- a lone CR inside a word, as a wrap hint.

    `community.clean` only normalises the `\\r\\n` PAIR, and `_WS` matched a bare
    `\\r`, so it became a space mid-word: the card shipped
    `あの日社 長とけんかしたあげくに、会 社をやめた` and glued `長い時間rather` where the
    CR was the only separator between the Japanese and English halves of a line.
    Both were present identically in candidates v12, v17 and v18, so the visual
    gate had been scoring them for several rounds.

    The CR is normalised to the same soft wrap as a newline and then resolved by
    the language-aware rule, rather than being hard-coded to one outcome.
    """
    from bugd.richtext import _paragraphize

    assert (_paragraphize("◆ × あの日\n社\r長\nとけんかしたあげくに、\n会\r社\nをやめた。")
            == "◆ × あの日社長とけんかしたあげくに、会社をやめた。")
    # Same CR, opposite verdict: a script change still needs its space.
    assert (_paragraphize("such as いろいろ, or 長い時間\rrather than about")
            == "such as いろいろ, or 長い時間 rather than about")
    # A normal CRLF is still just a line break.
    assert _paragraphize("line one\r\nline two") == "line one line two"


def test_an_unbulleted_variant_list_keeps_one_item_per_line():
    """These sources publish a variant list with one item per line and no bullet.

    The Japanese-join rule glued them into an unreadable run --
    `食べっぷり飲みっぷり言いっぷり走りっぷり…` -- because a wrap between two Japanese
    characters is normally not a break. Line LENGTH cannot tell the two apart: a
    wrapped sentence (`告白しようとしたが、` / `いざとなると`) is just as short. The
    repeated grammar point can: list items share a trailing run, a wrapped
    sentence shares none.
    """
    from bugd.richtext import _paragraphize

    assert (_paragraphize("食べっぷり\n飲みっぷり\n言いっぷり\n仕事っぷり など")
            == "食べっぷり\n飲みっぷり\n言いっぷり\n仕事っぷり など")
    assert (_paragraphize("愛してやまない\n尊敬してやまない\n期待してやまない など")
            == "愛してやまない\n尊敬してやまない\n期待してやまない など")
    # The LAST item carries a closing remark, which destroys the shared tail while
    # the item is still an item; its leading word is compared as well.
    assert (_paragraphize("言いっぷり\n仕事っぷり など…（「〜ぶり」に書き換えOK）")
            == "言いっぷり\n仕事っぷり など…（「〜ぶり」に書き換えOK）")

    # A wrapped SENTENCE has no repeated tail, so it still joins.
    assert (_paragraphize("告白しようとしたが、\nいざとなると\n何も言えなくなった")
            == "告白しようとしたが、いざとなると何も言えなくなった")
    # A one-character shared tail is not parallelism: almost every Japanese line
    # ends in `だ`, `る` or `い`.
    assert _paragraphize("これは丁寧\nとても便利") == "これは丁寧とても便利"


def test_adjacent_construction_patterns_each_keep_their_line():
    """The producer publishes its slot notation one pattern per line.

    The shared-tail rule cannot see these, because two patterns for the same point
    legitimately end differently -- `あまり／あんまり＋イ形容詞語幹＋くない` next to
    `あまり＋動ない形` -- so they fused into `…くないあまり＋動ない形`.

    The FULLWIDTH PLUS is the corpus's slot join, and it is the signal. The rule
    requires BOTH sides to be notation only: a numbered explanation sentence can
    quote a pattern too, and must keep wrapping like the prose it is.
    """
    from bugd.richtext import _paragraphize

    assert (_paragraphize("あまり／あんまり＋イ形容詞語幹＋くない\nあまり＋動ない形")
            == "あまり／あんまり＋イ形容詞語幹＋くない\nあまり＋動ない形")
    assert (_paragraphize("動意向形＋としない\n動意向形＋とはしない\n動意向形＋ともしない")
            == "動意向形＋としない\n動意向形＋とはしない\n動意向形＋ともしない")

    # A pattern followed by its EXPLANATION is a prose transition, not two
    # patterns, so the rule must not fire.
    assert (_paragraphize("Ｖます＋終わる\n継続する動作が終わるという意味")
            == "Ｖます＋終わる継続する動作が終わるという意味")
    # A numbered sentence quoting a pattern is prose: it ends in `。` and opens
    # with an enumerator, so it is excluded on both counts.
    assert (_paragraphize("２）「～」は「形容詞の語幹＋さ」が多い。\n２）As in the examples")
            == "２）「～」は「形容詞の語幹＋さ」が多い。\n２）As in the examples")


def test_the_producers_in_prose_example_run_is_marked_for_styling():
    """Two sources write their examples inside the explanation field.

    They arrive as prose lines under the producer's own ［例］ heading, so they got
    none of the example styling that lifted `point.examples` items have, and round
    9 filed that twice as a must-fix ("example dialogue, derived-meaning arrows (→)
    and 【具体的な例】 annotations are not visually separated").

    Measured over the corpus: 739 prose fields carry the marker, mean 4.6 lines per
    block, and every block ends at a BLANK line -- so the run has an unambiguous
    end and the marking cannot bleed into the prose that follows it.
    """
    from bugd.banks import _paragraphs

    nodes = _paragraphs(
        "「〜くらい」は［軽視］を表します。\n"
        "［例］\n"
        "①ビールくらいしかありませんが\n"
        "②彼女：こんなものくらいしか作れなかった\n"
        "\n"
        "「くらい」がつく文型はたくさんあります"
    )
    roles = [tuple(n.get("data") or {}) for n in nodes]
    assert roles == [
        (),                  # ordinary prose before the marker
        ("exampleLabel",),   # the producer's own ［例］ heading
        ("inlineExample",),
        ("inlineExample",),
        (),                  # the blank line ended the run
    ]

    # A field with no marker is untouched, so nothing is styled speculatively.
    assert [tuple(n.get("data") or {}) for n in _paragraphs("一行目\n二行目")] == [(), ()]


def test_the_in_prose_example_run_ends_at_the_producers_closing_remark():
    """`bugd.richtext` collapses the blank line that ends the producer's run.

    `_PARA_BREAK` writes ONE sentinel per run of newlines, so by the time
    `_paragraphs` sees the text the blank line separating the examples from the
    prose after them is gone. Round 10's real-host screenshot caught the
    consequence directly: the tinted block swallowed the closing explanatory
    sentence AND the 【関連文法】 heading that followed it, so a section label
    rendered as if it were example content.

    The run therefore ends on signals that survive into the node stream.
    """
    from bugd.banks import _ends_example_run

    # Example content: enumerated items and `→` derivations.
    assert not _ends_example_run("①ビールくらいしかありませんが")
    assert not _ends_example_run("→最低限、電話はしなさい")
    # A dialogue turn ends like a sentence but is still example content; closing
    # here would orphan the `夫：` reply outside the block.
    assert not _ends_example_run("妻：もう１０時よ！早く起きて！！")
    assert not _ends_example_run("夫：日曜日くらい寝させてくれよ…")

    # A section heading is never example content.
    assert _ends_example_run("【関連文法】")
    # The producer's closing remark. It often carries NO sentence punctuation at
    # all, only a polite ending and an emoji -- which is what over-ran in round 10.
    assert _ends_example_run("「くらい」がつく文型はたくさんありますので、復習をしておきましょう😀")
    assert _ends_example_run("N１を受ける人はしっかりと覚えておきましょう😊")
    assert _ends_example_run("一緒に覚えておきましょう")


def test_the_example_run_stays_boxed_across_its_whole_set():
    """Every specimen of one ［例］ run gets the box, not just the first.

    UGD-08c filed inconsistent boxing three times (findings 3, 6, 7): on あまり and
    くらい some example runs sat in the tinted well and others rendered as plain
    prose. Three producer shapes closed the run early:

    * the FIRST content line ends like a sentence (`差し支えなければ…ですか？`), so the
      run closed on its own opening line -- 69 runs / 62 edewakaru fields;
    * a `【「X」は動詞】` per-example annotation between two circled examples read as a
      section heading and closed the run -- 89 occurrences / 27 fields;
    * enumerator-less parallel example sentences (`学校まで、どのくらいかかるの？`) each end
      in `？`, so `_EXAMPLE_RUN_CLOSER` dropped the whole set.

    The property: within one run, every specimen, its `→` derivation and its
    per-example `【…】` annotation carry `inlineExample`, and only the producer's
    genuine closing remark / section heading falls outside.
    """
    from bugd.banks import _ends_example_run, _paragraphs

    # 3c: the first content line is a specimen even when it ends like a sentence.
    assert _ends_example_run("差し支えなければ、お名前を教えていただけますか？", is_first=True) is False
    # But the same line as a NON-first boundary followed by a heading still closes.
    assert _ends_example_run(
        "「くらい」の用法はたくさんあります。", next_line="【関連記事】"
    ) is True

    # 3b: a bracketed annotation followed by another example item keeps the run open;
    # a real section heading followed by prose closes it.
    assert _ends_example_run("【「持つ」は動詞】", next_line="②この本はあまりおもしろくない") is False
    assert _ends_example_run("【関連文型】", next_line="「あまり」はN５の文型です") is True

    # 3c: a parallel example variant sharing a leading stem with its neighbour is
    # not the closing remark; the LAST variant is kept via the previous-line stem.
    assert _ends_example_run(
        "学校まで、どのくらいかかるの？", next_line="学校まで、どれくらいかかるの？"
    ) is False
    assert _ends_example_run(
        "学校まで、何時間くらいかかるの？",
        prev_line="学校まで、どれくらいかかるの？",
        next_line="「〜くらい」には、いくつかの用法があります😉",
    ) is False
    # A closing remark that merely ends like a sentence and shares no stem closes.
    assert _ends_example_run(
        "「〜くらい」には、いくつかの用法があります😉",
        prev_line="学校まで、何時間くらいかかるの？",
        next_line="【関連記事】",
    ) is True

    # End to end through _paragraphs: the enumerator-less parallel set is fully boxed
    # and the closing remark plus headings fall outside.
    nodes = _paragraphs(
        "「〜くらい」は「だいたい〜」という意味です。\n"
        "［例］\n"
        "学校まで、どのくらいかかるの？\n"
        "学校まで、どれくらいかかるの？\n"
        "学校まで、何時間くらいかかるの？\n"
        "「〜くらい」には、いくつかの用法がありますので復習しておきましょう😉\n"
        "【関連記事】"
    )
    roles = [tuple(n.get("data") or {}) for n in nodes]
    assert roles == [
        (),                  # the lead-in prose
        ("exampleLabel",),   # ［例］
        ("inlineExample",),  # 学校まで … どの
        ("inlineExample",),  # 学校まで … どれ
        ("inlineExample",),  # 学校まで … 何時間  <- previously fell out of the box
        (),                  # the producer's closing remark
        ("proseHeading",),   # 【関連記事】
    ]


def test_a_producer_section_marker_before_the_first_speaker_is_not_a_turn():
    """edewakaru writes `［例］ A：…B：…` and `（デパートで）客：…`.

    The bracketed prefix is a section marker or stage direction, so the run is
    still a transcript -- but the marker must not be torn onto its own line, and
    the first speaker must not get a leading break.
    """
    from bugd.banks import _split_dialogue_turns

    assert _split_dialogue_turns("［例］ A：得意な料理は何？B：カップラーメンかな") == [
        "［例］ A：得意な料理は何？", {"tag": "br"}, "B：カップラーメンかな",
    ]
    assert _split_dialogue_turns(
        "（デパートで）客：このスカートをはいてみてもいいですか。店員：どうぞ"
    ) == [
        "（デパートで）客：このスカートをはいてみてもいいですか。",
        {"tag": "br"},
        "店員：どうぞ",
    ]

    # A bracketed prefix does NOT make ordinary prose a transcript.
    assert (_split_dialogue_turns("［例］ この文型は丁寧です。")
            == "［例］ この文型は丁寧です。")


def test_dialogue_examples_reach_the_built_card_as_separate_lines():
    point = GrammarPoint(
        source="s",
        source_id="1",
        expression="くらい",
        meaning="about",
        examples=(Example(japanese="A:\u3044\u304f\u3089\uff1f\u2003\u2003B:\u767e\u5186", english="A: how much?\u2003\u2003B: 100 yen"),),
    )
    row = build_term_entry(MergedEntry(expression="くらい", contributions=[point]), 1)
    blob = json.dumps(row, ensure_ascii=False)
    assert "\u2003\u2003" not in blob
    assert '"br"' in blob


# --------------------------------------------- UGD-08b per-source JLPT level


def _source_disclosures(row: list) -> list[dict]:
    """Every `sourceBlock` disclosure in a built row, in render order."""
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("tag") == "details" and "sourceBlock" in (node.get("data") or {}):
                found.append(node)
            walk(node.get("content"))
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(row[5])
    return found


def _levels_in(node) -> list[str]:
    """Every `jlpt`-role value inside a node subtree, in render order."""
    found: list[str] = []

    def walk(current):
        if isinstance(current, dict):
            if "jlpt" in (current.get("data") or {}):
                content = current.get("content")
                if isinstance(content, str):
                    found.append(content)
            walk(current.get("content"))
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(node)
    return found


def _summary_of(disclosure: dict) -> dict:
    return disclosure["content"][0]


def test_each_source_states_its_own_jlpt_level_inside_its_disclosure():
    """A cross-source level disagreement must be readable, not collapsed.

    158 unified entries carry more than one level, each attributed to a named
    source. The compact badge is deliberately ONE line and takes the first
    contribution that supplies a level, so before this the `あまり` card showed a
    single badge while `N2` and `N3` appeared nowhere in the packaged bytes — a
    learner reading the 絵でわかる日本語 section could not tell that source called
    it N2 while 毎日のんびり日本語教師 called it N3.

    Neither level is reconciled, voted on, or preferred: both statements are true
    about their own source, so each is stated where that source speaks.
    """
    n2 = _point(source="edewakaru", source_id="a", jlpt="N2", explanation="Ede.",
                provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]})
    n3 = _point(source="dojg", source_id="b", jlpt="N3", explanation="DoJG.")
    row = build_term_entry(MergedEntry(expression="あまり", contributions=[n2, n3]), 1)

    by_source = {
        _summary_of(d)["content"][0]["content"]: _levels_in(d["content"][1:])
        for d in _source_disclosures(row)
    }

    assert by_source == {
        SOURCE_LABELS["edewakaru"]: ["N2"],
        SOURCE_LABELS["dojg"]: ["N3"],
    }


def test_a_source_disclosure_states_its_level_exactly_once():
    """One source, several senses: the level belongs to the SOURCE, not each sense.

    Measured over the corpus, 160 of 207 multi-sense disclosures repeat the same
    level on every sense inside them (max repeats: 2 on 128, 3 on 23, 4 on 9). A
    per-sense badge would therefore stack the identical string up to four times
    inside one disclosure while adding no information.
    """
    senses = [
        _point(source_id="a", jlpt="N3", meaning="one", explanation="One."),
        _point(source_id="b", jlpt="N3", meaning="two", explanation="Two."),
        _point(source_id="c", jlpt="N3", meaning="three", explanation="Three."),
    ]
    row = build_term_entry(MergedEntry(expression="ない", contributions=senses), 1)

    disclosures = _source_disclosures(row)
    assert len(disclosures) == 1
    assert _levels_in(disclosures[0]["content"][1:]) == ["N3"]


def test_one_source_disagreeing_with_itself_shows_both_of_its_levels():
    """A source that ships two levels for one form must not silently lose one.

    `あまり` really does carry N2 AND N5 from edewakaru alone. Deduplicating per
    source must collapse REPEATS, never distinct assertions, and the order is the
    source's own contribution order rather than a sort.
    """
    senses = [
        _point(source_id="a", jlpt="N5", meaning="not much", explanation="One."),
        _point(source_id="b", jlpt="N2", meaning="excessively", explanation="Two."),
    ]
    row = build_term_entry(MergedEntry(expression="あまり", contributions=senses), 1)

    disclosures = _source_disclosures(row)
    assert len(disclosures) == 1
    assert _levels_in(disclosures[0]["content"][1:]) == ["N5", "N2"]


def test_a_source_asserting_only_a_level_still_gets_to_say_it():
    """7 of the 158 conflicts hid behind a source that renders no prose.

    On `たい`, `で`, `方`, `もう`, `てはいけない`, `たらどうですか` and
    `を余儀なくされる` the DISAGREEING source ships a level (and at most a meaning
    or structure the compact block already absorbed), so it produced no
    disclosure at all and its level was unreachable. A level is a substantive
    claim about the point, so it earns the source a disclosure of its own.
    """
    rich = _point(source="dojg", source_id="a", jlpt="N2", explanation="Rich.")
    level_only = _point(
        source="nihongo_net",
        source_id="b",
        jlpt="N5",
        meaning=None,
        structure=None,
        explanation=None,
        examples=(),
        provenance={"sourceLabel": "日本語NET JLPT文法解説まとめ"},
    )
    row = build_term_entry(MergedEntry(expression="たい", contributions=[rich, level_only]), 1)

    by_source = {
        _summary_of(d)["content"][0]["content"]: _levels_in(d["content"][1:])
        for d in _source_disclosures(row)
    }
    assert by_source == {
        SOURCE_LABELS["dojg"]: ["N2"],
        "日本語NET JLPT文法解説まとめ": ["N5"],
    }


def test_a_source_with_no_level_and_no_substance_earns_no_disclosure():
    """The level is what makes a bare record worth a row — not the record itself.

    Contract invariant 6 forbids a card whose only visible content is the Sources
    disclosure, and invariant 4 forbids a row carrying BOTH a sourceBlock and a
    compact fallback. Admitting substance-less records wholesale would break
    both, so admission is gated on the level itself.
    """
    bare = _point(
        source="edewakaru", source_id="b", jlpt=None, meaning=None, structure=None,
        explanation=None, examples=(),
        provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]},
    )
    rich = _point(source="dojg", source_id="a", explanation="Rich.")
    row = build_term_entry(MergedEntry(expression="x", contributions=[rich, bare]), 1)

    labels = [
        _summary_of(d)["content"][0]["content"] for d in _source_disclosures(row)
    ]
    assert labels == [SOURCE_LABELS["dojg"]]


def test_the_level_row_is_the_only_thing_this_change_adds_to_a_card():
    """Containment: the level row must not perturb the rest of the card.

    This change touched the disclosure builder that every card goes through, so a
    regression here would silently reshape 2,441 cards. When the beauty gate
    returned 13 must-fix findings, this property is what allowed them to be
    attributed to the corpus rather than to this card: strip every `sourceLevel`
    node from the rendered output and the result must be exactly what the renderer
    produced before, with no reordering, no lost sense, and no changed prose.

    Asserted against the production composer rather than a fixture diff, so it
    keeps biting if `_source_blocks` is refactored.
    """
    def strip(node):
        if isinstance(node, list):
            return [
                strip(item) for item in node
                if not (isinstance(item, dict) and "sourceLevel" in (item.get("data") or {}))
            ]
        if isinstance(node, dict):
            copy = dict(node)
            if "content" in copy:
                copy["content"] = strip(copy["content"])
            return copy
        return node

    points = [
        _point(source="dojg", source_id="a", jlpt="N3", meaning="one", explanation="One."),
        _point(source="dojg", source_id="b", jlpt="N2", meaning="two", explanation="Two."),
        # Four senses from one source, i.e. exactly SENSES_PER_SOURCE, so a
        # truncation introduced alongside the level row cannot hide here (a
        # mutation dropping the bound to 3 survived a 2-sense fixture).
        _point(source="dojg", source_id="c", meaning="three", explanation="Three."),
        _point(source="dojg", source_id="d", meaning="four", explanation="Four."),
        _point(source="edewakaru", source_id="e", jlpt="N5", explanation="Five.",
               provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]}),
    ]
    entry = MergedEntry(expression="あまり", contributions=points)

    with_levels = build_term_entry(entry, 1)
    without = [_point(**{**dict(
        source=p.source, source_id=p.source_id, expression=p.expression,
        reading=p.reading, meaning=p.meaning, structure=p.structure,
        explanation=p.explanation, examples=p.examples, provenance=p.provenance,
    ), "jlpt": None}) for p in points]
    baseline = build_term_entry(MergedEntry(expression="あまり", contributions=without), 1)

    # The compact badge is fed by point.jlpt too, so compare below the fold only.
    stripped = strip(with_levels[5][0]["content"]["content"][1:])
    assert stripped == baseline[5][0]["content"]["content"][1:]
    # ...and the levels really were there to strip.
    assert _levels_in(with_levels[5][0]["content"]["content"][1:]) == ["N3", "N2", "N5"]
    # ...and every sense the bound allows still rendered its own body.
    blob = json.dumps(with_levels, ensure_ascii=False)
    for body in ("One.", "Two.", "Three.", "Four.", "Five."):
        assert blob.count(body) == 1, f"{body} rendered {blob.count(body)}x"


def test_a_per_source_level_never_replaces_the_compact_badge():
    """The compact block stays one line; the disclosures are the added surface."""
    n2 = _point(source="edewakaru", source_id="a", jlpt="N2", explanation="Ede.",
                provenance={"sourceLabel": SOURCE_LABELS["edewakaru"]})
    n3 = _point(source="dojg", source_id="b", jlpt="N3", explanation="DoJG.")
    row = build_term_entry(MergedEntry(expression="あまり", contributions=[n2, n3]), 1)

    compact = row[5][0]["content"]["content"][0]
    assert "compact" in compact["data"]
    assert _levels_in(compact) == ["N2"]


def test_a_per_source_level_is_labelled_so_a_bare_code_is_not_ambiguous():
    """`N2` alone inside a body of prose does not say what it measures.

    Above the fold the badge sits in a metadata row beside the construction chip
    and reads as card metadata. Inside a source's disclosure it would be a bare
    two-character code in running text, so it is introduced by the source's own
    claim.
    """
    point = _point(jlpt="N3", explanation="Prose.")
    row = build_term_entry(MergedEntry(expression="x", contributions=[point]), 1)

    disclosure = _source_disclosures(row)[0]
    blob = json.dumps(disclosure, ensure_ascii=False)
    assert "sourceLevel" in blob
    assert "JLPT" in blob


def test_the_per_source_level_row_is_visually_subordinate_to_the_prose():
    """It is provenance about the source's claim, not the claim itself.

    A per-source level set at body size and weight would compete with the
    explanation it annotates on 158 cards, so it is declared quieter and smaller
    while still clearing the card's contrast floor via `--bugd-muted` (which the
    de-emphasis-token test already gates at 4.5:1 on the card's own surfaces).
    """
    import re

    from conftest import resolve_space_tokens

    css = resolve_space_tokens(STYLES_CSS)
    rule = re.search(r"\[data-sc-source-level\]\s*\{([^}]*)\}", css)
    assert rule, "the per-source level row needs its own rule"
    block = rule.group(1)

    size = re.search(r"font-size:\s*([0-9.]+)em", block)
    assert size and float(size.group(1)) < 1.0, (
        f"a provenance row must not be body size (got {block!r})"
    )
    assert "var(--bugd-muted)" in block


# ------------------------------------------------------ UGD-14 visual gate


def _sense_labels(row: list) -> list[str]:
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "senseLabel" in (node.get("data") or {}):
                content = node.get("content")
                if isinstance(content, str):
                    found.append(content)
            walk(node.get("content"))
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(row[5])
    return found


def test_the_compact_headline_is_not_repeated_as_the_first_sense_label():
    """The compact meaning is selected FROM the first contribution, so before this
    the first sense label reproduced it verbatim ~15px below it (measured on くらい
    in the real host). A differing label must still be kept."""
    first = _point(source_id="a", meaning="Approximately; about", explanation="One.")
    second = _point(source_id="b", meaning="To the extent that", explanation="Two.")
    row = build_term_entry(
        MergedEntry(expression="くらい", contributions=[first, second]), 1
    )
    labels = _sense_labels(row)

    assert "Approximately; about" not in labels
    assert "To the extent that" in labels


def test_a_repeated_headline_does_not_collapse_the_other_sense_labels():
    """Dropping the duplicate must not renumber or hide the remaining senses."""
    points = [
        _point(source_id="a", meaning="same", explanation="One."),
        _point(source_id="b", meaning="same", explanation="Two."),
        _point(source_id="c", meaning="different", explanation="Three."),
    ]
    row = build_term_entry(MergedEntry(expression="x", contributions=points), 1)
    labels = _sense_labels(row)

    # Both "same" senses lose their label (they repeat the visible headline);
    # the distinguishing one keeps it.
    assert labels == ["different"]
    # All three senses still render their own body.
    assert json.dumps(row, ensure_ascii=False).count("Three.") == 1


def test_every_disclosure_row_carries_the_stronger_control_edge():
    """A 1px #eee edge on white measured identical on every summary yet still read
    as 'one row is boxed, the next has none' in real-host review. The control edge
    is deliberately stronger than the generic hairline rule."""
    assert "--bugd-control-edge:" in STYLES_CSS
    details_rule = STYLES_CSS.split("[data-sc-grammar-card] details {")[1].split("}")[0]
    assert "border: 1px solid var(--bugd-control-edge)" in details_rule
    # The hairline rule must NOT be what draws a control boundary any more.
    assert "border: 1px solid var(--bugd-rule)" not in details_rule


def test_the_disclosure_box_encloses_the_disclosed_body():
    """The border must wrap the whole `details`, not only its `summary`.

    Round 6 of the beauty gate filed three must-fix reports on the two sparse
    entries: "the Sources box expands to a large empty region and the
    'Contributed by ...' text sits outside the bordered box". A DOM probe in real
    Yomitan 26.8.24.0 disproved the stated mechanism -- the attribution measured
    `insideDetails: true` -- but confirmed the appearance: the box was drawn on
    the 54px summary alone, so every disclosed body (29px on 相まって/あいにく,
    1231px on 間) rendered BELOW the border and the control looked like an empty
    shell followed by loose text.

    So the surface belongs on `details`; `summary` keeps only the hover/idle
    tint that distinguishes the clickable row from the body it reveals.
    """
    details_rule = STYLES_CSS.split("[data-sc-grammar-card] details {")[1].split("}")[0]
    assert "border: 1px solid var(--bugd-control-edge)" in details_rule
    assert "border-radius" in details_rule

    summary_rule = STYLES_CSS.split("[data-sc-grammar-card] summary {")[1].split("}")[0]
    # The summary must NOT draw its own full box any more, or the open state
    # shows a border between the control and the body it disclosed.
    assert "border: 1px solid" not in summary_rule


def _relative_luminance(rgb):
    def channel(value):
        v = value / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _composite(fg, alpha, bg):
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def test_the_control_edge_clears_the_ui_component_contrast_floor():
    """The disclosure boundary must actually be visible on BOTH Yomitan surfaces.

    Three separate real-host review rounds filed "the collapsible row has no
    visible box/border" as a must-fix while the CSS demonstrably drew one on every
    row (a DOM probe measured all 18 rows resolving to ONE computed style). The
    defect was never consistency -- it was that a translucent hairline composited
    to too little contrast to register as a boundary at all.

    So the assertion is on the MEASURED composited contrast, not on the literal
    token: a value can be edited without anyone re-deriving whether it is still
    visible. 3:1 is the standard non-text floor for a UI component boundary.

    Yomitan's own surfaces are white in its light theme and rgb(30,30,30) in its
    dark theme (`ext/css/display.css`); the token has to work against both,
    because this stylesheet is wrapped in `[data-dictionary=...]` and therefore
    cannot match `:root[data-theme=dark]` to pick a per-theme colour.
    """
    import re

    match = re.search(
        r"--bugd-control-edge:\s*rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)",
        STYLES_CSS,
    )
    assert match, "--bugd-control-edge must be a literal rgba() the theme can composite"
    grey = tuple(int(match.group(i)) for i in (1, 2, 3))
    alpha = float(match.group(4))

    for surface, name in (((255, 255, 255), "light"), ((30, 30, 30), "dark")):
        edge = _composite(grey, alpha, surface)
        ratio = _contrast(edge, surface)
        assert ratio >= 3.0, (
            f"control edge composites to {edge} on the {name} surface, only "
            f"{ratio:.2f}:1 against it -- below the 3:1 UI-component floor, which "
            f"is what review kept reporting as 'no visible boundary'"
        )


def test_the_resting_control_fill_is_a_distinct_surface():
    """A control row needs a resting fill, not only a hover state.

    The fill is deliberately quiet -- it is a well, not a button -- but it must be
    distinguishable from the card background it sits on, in both themes. At the
    original 0.09 alpha it composited to rgb(243,243,243) on white for 1.11:1,
    which is not a perceptible surface change.
    """
    import re

    match = re.search(
        r"--bugd-well:\s*rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", STYLES_CSS
    )
    assert match, "--bugd-well must be a literal rgba()"
    grey = tuple(int(match.group(i)) for i in (1, 2, 3))
    alpha = float(match.group(4))

    for surface, name in (((255, 255, 255), "light"), ((30, 30, 30), "dark")):
        fill = _composite(grey, alpha, surface)
        ratio = _contrast(fill, surface)
        assert ratio >= 1.15, (
            f"resting fill composites to {fill} on the {name} surface, only "
            f"{ratio:.2f}:1 -- indistinguishable from the card background"
        )
        # And it must stay a QUIET well: a fill this size competing with the
        # label would be worse than none.
        assert ratio <= 1.6, f"resting fill is too loud on {name}: {ratio:.2f}:1"

    hover = re.search(
        r"--bugd-well-hover:\s*rgba\(\s*\d+,\s*\d+,\s*\d+,\s*([0-9.]+)\s*\)", STYLES_CSS
    )
    assert hover, "--bugd-well-hover must be a literal rgba()"
    assert float(hover.group(1)) > alpha, "hover must be stronger than the resting fill"


def test_a_producers_bracketed_section_line_renders_as_a_heading():
    """The producers write subsection headings inline, fully bracketed.

    Every prose paragraph used to be emitted as an identical body-weight `div`, so
    `【関連文型】` and `［使い分け］` carried no more visual weight than the sentences
    around them. Round 9's visual gate made that its dominant finding: 30 of 92
    images scored below 8 and their notes name it directly -- "the 【...】
    bracket-style headers", "text hierarchy is mostly flat", "a dense wall of
    Japanese text with little differentiation", "lacks visual hierarchy".

    Measured over the packaged v23 banks: 917 `【…】` plus 206 `［…］` heading lines
    against 18,897 body lines, so this is a corpus-wide data-shape defect.
    """
    from bugd.banks import _paragraphs, _prose_paragraph

    for heading in ("【関連文型】", "【上級レベルの人へ】", "［使い分け］", "〈注意〉", "【◯＋数量詞】"):
        node = _prose_paragraph(heading)
        assert (node.get("data") or {}).get("proseHeading") == "", f"{heading!r} must be a heading"
        # The producer's own brackets are KEPT: stripping them would silently
        # edit source text. Only the rendering weight changes.
        assert node["content"] == heading

    # A sentence that merely CONTAINS bracketed text is body prose, not a heading.
    for body in (
        "「だって」は理由を聞かれた時の答えとして使われます",
        "【関連文型】と【類似文型】はどちらも参考になります",
        "これは【重要】な文型です。",
        "【】",
    ):
        assert "proseHeading" not in (_prose_paragraph(body).get("data") or {}), body

    # The ［例］ marker collides with the heading pattern but is handled first, so
    # it must keep its own role and must never be tagged as a heading too.
    nodes = _paragraphs("説明文です。\n［例］\n①これは例です\n\n【関連文型】\n次も見てください。")
    roles = [tuple(sorted(n.get("data") or {})) for n in nodes]
    assert roles == [
        (),
        ("exampleLabel",),
        ("inlineExample",),
        ("proseHeading",),
        (),
    ]


def test_the_prose_heading_is_styled_as_a_landmark():
    """A heading must outweigh the body it introduces, not merely differ from it."""
    import re

    from bugd.styles import STYLES_CSS

    from conftest import resolve_space_tokens

    css = resolve_space_tokens(STYLES_CSS)
    block = re.search(r"\[data-sc-prose-heading\]\s*\{([^}]*)\}", css)
    assert block, "the prose heading needs its own rule"
    body = block.group(1)
    weight = re.search(r"font-weight:\s*(\d+)", body)
    assert weight and int(weight.group(1)) >= 700, "a heading needs bold weight"
    size = re.search(r"font-size:\s*([0-9.]+)em", body)
    assert size and float(size.group(1)) >= 1.0, "a heading must not be smaller than body text"
    # Leading above is what actually breaks the wall of text into sections.
    top = re.search(r"margin-top:\s*([0-9.]+)em", body)
    assert top and float(top.group(1)) >= 0.8, "a heading needs space above it"
    # A heading must not be quieter than its body: --bugd-muted/--bugd-quiet are
    # the de-emphasis tokens and would invert the hierarchy.
    assert "--bugd-muted" not in body and "--bugd-quiet" not in body


def test_the_highlighted_grammar_point_is_never_split_across_a_line_wrap():
    """Round 9 must-fix: `くらい` wrapped as `...歩けないくら` / `いだ`.

    `[data-sc-prose]` sets `overflow-wrap: anywhere` so long Japanese can break
    inside a 320px popup, and that permission reached the highlighted span too --
    splitting the one string on the card the reader is looking for.

    Held on one line, EXCEPT when a producer marks a whole sentence: those cannot
    be held unbroken without overflowing the popup, so containment wins. CSS
    cannot measure text length, so the generator makes that call. Measured over
    the packaged banks: 6,079 spans, 6,072 within budget and 7 above (20-60).
    """
    import re

    from bugd.banks import HIGHLIGHT_NOWRAP_BUDGET, _highlight_sentence
    from bugd.styles import STYLES_CSS

    def spans(node):
        if isinstance(node, dict):
            data = node.get("data") or {}
            if "hl" in data:
                yield data, node.get("content")
            yield from spans(node.get("content"))
        elif isinstance(node, list):
            for item in node:
                yield from spans(item)

    short = list(spans(_highlight_sentence("もう1歩も歩けないくらいだ", ("くらい",))))
    assert [c for _, c in short] == ["くらい"]
    assert "hlLong" not in short[0][0], "an ordinary highlight must stay unbreakable"

    sentence = "「だって」は理由を聞かれた時の答えとして「なぜかというと」の意味で使われます"
    assert len(sentence) > HIGHLIGHT_NOWRAP_BUDGET
    long_spans = list(spans(_highlight_sentence(sentence, (sentence,))))
    assert long_spans and long_spans[0][0].get("hlLong") == "", (
        "a sentence-length highlight must be allowed to wrap or it overflows the popup"
    )

    block = re.search(r"\[data-sc-hl\]\s*\{([^}]*)\}", STYLES_CSS)
    assert block and "white-space: nowrap" in block.group(1)
    escape = re.search(r"\[data-sc-hl-long\]\s*\{([^}]*)\}", STYLES_CSS)
    assert escape, "the long-highlight escape needs its own rule"
    assert "white-space: normal" in escape.group(1)
    # `normal` alone would still overflow: Japanese has no spaces to break on.
    assert "overflow-wrap: anywhere" in escape.group(1)


def test_any_bracketed_section_heading_ends_the_in_prose_example_run():
    """A `［…］` heading ends the run too, not only a `【…】` one.

    The narrower `【…】`-only check left `［説明］` and `［「〜ようだ」の形］` inside the
    tinted example block, where they came out carrying an example role AND a
    heading role simultaneously. Caught by verifying the PACKAGED bytes rather
    than the source, on 3 entries (ないものだ, ものだ, ようだ).
    """
    from bugd.banks import _ends_example_run, _paragraphs

    assert _ends_example_run("［説明］")
    assert _ends_example_run("［「〜ようだ」の形］")
    assert _ends_example_run("【関連文法】")
    # The ［例］ marker OPENS a run, so it must never be read as ending one.
    assert not _ends_example_run("［例］")
    assert not _ends_example_run("［例文］")

    nodes = _paragraphs("［例］\n①これは例です\n［説明］\nこれが説明です。")
    roles = [tuple(sorted(n.get("data") or {})) for n in nodes]
    assert roles == [("exampleLabel",), ("inlineExample",), ("proseHeading",), ()]
    # No node may ever hold both roles at once.
    for node in nodes:
        keys = set(node.get("data") or {})
        assert not ({"inlineExample", "exampleLabel"} & keys and "proseHeading" in keys)


def test_a_bracketed_label_leading_its_own_line_is_emphasised_inline():
    """`【変化】日本語が話せなかった→…` is a lead-in, not a heading.

    The whole-line heading rule deliberately does not match it, and reviewing a
    real-host v25 tile with vision caught the consequence: `【具体的な例】涙が出る程度`
    still rendered at body weight, indistinguishable from the sentences around it
    -- the same flat hierarchy round 9 filed. Measured over the packaged v25
    banks: 868 inline-prefix labels against 896 whole-line headings, so handling
    only the standalone shape would have covered half the corpus.
    """
    import re

    from bugd.banks import _prose_paragraph
    from bugd.styles import STYLES_CSS

    node = _prose_paragraph("【変化】日本語が話せなかった→日本語が話せる")
    # A lead-in stays one paragraph: it must NOT become a block heading.
    assert "proseHeading" not in (node.get("data") or {})
    parts = node["content"]
    assert isinstance(parts, list)
    label = parts[0]
    assert (label.get("data") or {}) == {"proseLabel": ""}
    # The producer's own brackets are kept verbatim.
    assert label["content"] == "【変化】"
    # The content after the label survives, unedited.
    rest = "".join(p for p in parts[1:] if isinstance(p, str))
    assert "日本語が話せなかった" in rest

    # A label with nothing after it is a whole-line heading, not a lead-in.
    assert (_prose_paragraph("【変化】").get("data") or {}).get("proseHeading") == ""
    # A bracket appearing mid-sentence is not a label.
    mid = _prose_paragraph("これは【重要】な文型です。")
    assert not (isinstance(mid["content"], list)
                and isinstance(mid["content"][0], dict)
                and "proseLabel" in (mid["content"][0].get("data") or {}))

    block = re.search(r"\[data-sc-prose-label\]\s*\{([^}]*)\}", STYLES_CSS)
    assert block, "the inline prose label needs its own rule"
    weight = re.search(r"font-weight:\s*(\d+)", block.group(1))
    assert weight and int(weight.group(1)) >= 700
    # A label that breaks across lines cannot serve as a scanning anchor.
    assert "white-space: nowrap" in block.group(1)


def test_a_wrapped_example_continuation_is_inset_not_flush_left():
    """A flush-left continuation reads as a new example.

    Reviewing a real-host v25 tile: `もう１歩も歩けないくらいだ` wrapped to a bare
    `らいだ` sitting exactly where the next example's first character sits, so the
    reader cannot tell a continuation from a new item by position.
    """
    import re

    from bugd.styles import STYLES_CSS

    block = re.search(r"\[data-sc-inline-example\]\s*\{([^}]*)\}", STYLES_CSS)
    assert block, "the inline example needs its own rule"
    body = block.group(1)
    indent = re.search(r"text-indent:\s*(-[0-9.]+)em", body)
    assert indent, "a hanging indent needs a NEGATIVE text-indent"
    hang = -float(indent.group(1))
    pad = re.search(r"padding-left:\s*([0-9.]+)em", body)
    assert pad, "the hanging indent needs padding-left to hang into"
    # The padding must absorb the negative indent or the first line pokes out of
    # the block, past its own left rule.
    assert float(pad.group(1)) >= hang, (
        f"padding-left {pad.group(1)}em cannot absorb a {hang}em hang"
    )


def test_a_derived_meaning_is_subordinated_to_its_specimen():
    """`→とても疲れた` belongs to the sentence above it, not beside it.

    Reviewed at 7/10, this was the single named remaining improvement: specimen and
    paraphrase rendered identically, so a derived meaning read as a peer, and
    because the gap inside an example set equalled the gap between sets, proximity
    carried no grouping information. Measured 1,416 derivation lines against 3,339
    specimens in the packaged v26 banks.
    """
    import re

    from bugd.banks import _paragraphs
    from bugd.styles import STYLES_CSS

    nodes = _paragraphs(
        "［例］\n①今日は歩き疲れた。もう１歩も歩けないくらいだ\n→とても疲れた\n②彼女くらい話せるようになりたい\n＝だいたい彼女と同じ程度\n"
    )
    roles = [tuple(sorted(n.get("data") or {})) for n in nodes]
    assert roles == [
        ("exampleLabel",),
        ("inlineExample",),
        ("exampleDerivation", "inlineExample"),
        ("inlineExample",),
        ("exampleDerivation", "inlineExample"),
    ]
    # `＝` counts as a derivation too: the producer uses both glyphs.
    # A derivation is still part of the run, so it must keep the example role.
    for node in nodes[1:]:
        assert "inlineExample" in (node.get("data") or {})

    from conftest import resolve_space_tokens

    css = resolve_space_tokens(STYLES_CSS)
    block = re.search(r"\[data-sc-example-derivation\]\s*\{([^}]*)\}", css)
    assert block, "a derivation needs its own rule"
    body = block.group(1)
    deriv_pad = re.search(r"padding-left:\s*([0-9.]+)em", body)
    assert deriv_pad, "a derivation must be indented"

    base = re.search(r"\[data-sc-inline-example\]\s*\{([^}]*)\}", STYLES_CSS)
    base_pad = re.search(r"padding-left:\s*([0-9.]+)em", base.group(1))
    # It must sit to the RIGHT of the specimen it derives from, or the hierarchy
    # is inverted -- which is exactly what the review measured.
    assert float(deriv_pad.group(1)) > float(base_pad.group(1)), (
        f"derivation indent {deriv_pad.group(1)}em must exceed specimen "
        f"{base_pad.group(1)}em"
    )
    # And it must be visibly quieter than its specimen.
    assert "--bugd-quiet" in body or "--bugd-muted" in body

    # Proximity must group: the next SPECIMEN gets air, the derivation does not.
    gap = re.search(
        r"\[data-sc-prose\] :is\(\[data-sc-example-derivation\], "
        r"\[data-sc-example-annotation\]\) \+ \[data-sc-inline-example\]"
        r":not\(\[data-sc-example-derivation\]\):not\(\[data-sc-example-annotation\]\)\s*\{([^}]*)\}",
        css,
    )
    assert gap, "a new example set needs a gap above it"
    top = re.search(r"margin-top:\s*([0-9.]+)em", gap.group(1))
    assert top
    # The step must be big enough to read as a new group without measuring it. The
    # review scored a 0.5em step against the 0.55em paragraph rhythm as only ~15%
    # more, "well below the ~1.5-2x step that reads as a new group".
    para = re.search(r"\[data-sc-prose\] div \+ div \{[^}]*margin-top:\s*([0-9.]+)em", css)
    assert para
    assert float(top.group(1)) >= 1.5 * float(para.group(1)), (
        f"inter-set gap {top.group(1)}em is not a clear step over the "
        f"{para.group(1)}em intra-set rhythm"
    )


def test_a_producer_annotation_stays_attached_to_the_set_it_describes():
    """`【具体的な例】涙が出る程度` closes its set; the grouping gap must not land on it.

    The extracted source order is specimen, derivation, annotation, next specimen.
    With only the derivation on the left of the adjacency rule, the gap fell above
    the ANNOTATION -- detaching it from the ③ example it describes, gluing it to
    ④, and leaving the last annotation looking like an example-less orphan block.
    Reviewing the v27 real-host tile reported that as "labels off by one"; it was
    this one selector, not a source-order defect.
    """
    import re

    from bugd.banks import _paragraphs
    from bugd.styles import STYLES_CSS

    nodes = _paragraphs(
        "［例］\n"
        "③N１に合格して、涙が出るくらいうれしかった\n"
        "→とてもうれしかった\n"
        "【具体的な例】涙が出る程度\n"
        "④今日は歩き疲れた。もう１歩も歩けないくらいだ\n"
    )
    roles = [tuple(sorted(n.get("data") or {})) for n in nodes]
    assert roles == [
        ("exampleLabel",),
        ("inlineExample",),
        ("exampleDerivation", "inlineExample"),
        ("exampleAnnotation", "inlineExample"),
        ("inlineExample",),
    ]
    # An annotation is neither a specimen nor a derivation: it must not be double
    # tagged, or the adjacency rule cannot tell the three apart.
    ann = nodes[3]["data"]
    assert "exampleDerivation" not in ann

    block = re.search(r"\[data-sc-example-annotation\]\s*\{([^}]*)\}", STYLES_CSS)
    assert block, "an annotation needs its own rule"
    # Quieted like a derivation, since it is also secondary to the specimen.
    assert "--bugd-quiet" in block.group(1) or "--bugd-muted" in block.group(1)


def test_an_english_translation_line_is_subordinated_to_its_japanese():
    """A translation inside a Japanese field must not look like primary content.

    Reviewing a 7/10 v28 tile: `２）基本的に、名詞につく場合は…` and `２）Generally,
    くらい becomes ぐらい…` rendered at identical size, weight, colour and indent, so
    the reader could not tell a translation from the explanation it translates --
    and because the producer emits all the numbered Japanese points and then all
    the numbered English ones, the visible numerals appeared to run 2,1,2,1,3.
    Measured 1,412 such lines in the packaged v28 banks.

    `_lang_of` cannot answer this: it asks "is there ANY Japanese here", and a
    translation habitually quotes the Japanese it explains.
    """
    import re

    from bugd.banks import _is_latin_dominant, _lang_of, _prose_paragraph
    from bugd.styles import STYLES_CSS

    translation = "２）Generally, くらい becomes ぐらい when appended to nouns."
    # The exact trap: the existing field-level classifier calls this Japanese.
    assert _lang_of(translation) == "ja"
    assert _is_latin_dominant(translation)

    node = _prose_paragraph(translation)
    assert (node.get("data") or {}).get("proseTranslation") == ""
    # A translation must declare its own language or it inherits the card's `ja`.
    assert node.get("lang") == "en"

    # Japanese lines stay primary, including ones quoting Latin tokens.
    for japanese in (
        "２）基本的に、名詞につく場合は「ぐらい」を使う。",
        "③N１に合格して、涙が出るくらいうれしかった",
        "「イA」と「ナA」の違いに注意しましょう。",
        "Ａ：おいしいね！",
    ):
        assert not _is_latin_dominant(japanese), japanese
        assert "proseTranslation" not in (_prose_paragraph(japanese).get("data") or {}), japanese

    # A short Latin run is below the floor, so it cannot flip a Japanese line.
    assert not _is_latin_dominant("N1")
    assert not _is_latin_dominant("ＮＰ＋くらい")

    block = re.search(
        r"^\[data-sc-prose-translation\]\s*\{([^}]*)\}", STYLES_CSS, re.M
    )
    assert block, "a translation needs its own rule"
    body = block.group(1)
    assert re.search(r"padding-left:\s*[0-9.]+em", body), "a translation must be indented"
    assert "--bugd-quiet" in body or "--bugd-muted" in body, "a translation must be quieter"


def test_newline_separated_patterns_are_a_list_not_a_run_on_badge():
    """Three patterns separated by newlines must not be badged as one line.

    `_is_badge_structure` rejected only PIPE-delimited tables, but three of the
    four sources separate their patterns with a newline, and `_text` collapses
    whitespace -- so `名詞＋ほど＋名詞＋は～ない` + two variants arrived as one
    space-joined line that fit the compact budget and was badged. Round 13 filed it
    as a must-fix: "three grammar-pattern variants (ほど/くらい/ぐらい) are
    concatenated on a single line separated only by spaces". Measured 2,547
    multi-line structures over the extracted corpus, so this was corpus-wide.
    """
    from bugd.banks import (
        _construction_section,
        _has_badge_structure,
        _is_badge_structure,
        _text,
    )
    from bugd.model import GrammarPoint

    multi = "名詞＋ほど＋名詞＋は～ない\n名詞＋くらい＋名詞＋は～ない\n名詞＋ぐらい＋名詞＋は～ない"
    point = GrammarPoint(
        source="nihongo_no_sensei", source_id="ほど", expression="ほど", structure=multi
    )

    # The exact trap: collapsed to one line it still looks badge-worthy.
    assert _is_badge_structure(_text(multi))
    # The point-level check sees the newlines and refuses.
    assert not _has_badge_structure(point)

    section = _construction_section(point)
    assert section is not None, "a multi-pattern structure needs its Construction list"
    rows = section["content"]
    assert [r["content"] for r in rows] == [
        "名詞＋ほど＋名詞＋は～ない",
        "名詞＋くらい＋名詞＋は～ない",
        "名詞＋ぐらい＋名詞＋は～ない",
    ]
    # Source order is preserved; nothing is merged, sorted, or dropped.
    assert all("pattern" in (r.get("data") or {}) for r in rows)

    # A genuine single formula still earns its compact badge.
    single = GrammarPoint(
        source="edewakaru", source_id="間", expression="間",
        structure="〔普通形〕（ナＡな／Ｎの）＋間",
    )
    assert _has_badge_structure(single)
    assert _construction_section(single) is None


def test_a_multi_pattern_structure_is_never_used_as_a_sense_label():
    """The sense-label fallback is a third call site and leaked the same run-on.

    After the compact badge and the Construction list were both gated on source
    line count, round 14's real-host tile still showed
    `名詞＋ほど＋名詞＋は～ない 名詞＋くらい＋… 名詞＋ぐらい＋…` as one bold heading --
    because `_sense_label` tested the FLATTENED text, where the newlines are gone.
    """
    from bugd.banks import _sense_label
    from bugd.model import GrammarPoint

    multi = "名詞＋ほど＋名詞＋は～ない\n名詞＋くらい＋名詞＋は～ない\n名詞＋ぐらい＋名詞＋は～ない"
    point = GrammarPoint(
        source="nihongo_no_sensei", source_id="ほど", expression="ほど", structure=multi
    )
    label = _sense_label(point, ordinal=2, total=3)
    assert label == "Sense 2", f"a multi-pattern structure must not become a label: {label!r}"

    # A single formula is still a better label than a bare ordinal.
    single = GrammarPoint(
        source="edewakaru", source_id="間", expression="間",
        structure="〔普通形〕（ナＡな／Ｎの）＋間",
    )
    assert _sense_label(single, ordinal=2, total=3) == "〔普通形〕（ナＡな／Ｎの）＋間"
    # A lone sense needs no label at all.
    assert _sense_label(single, ordinal=1, total=1) == ""


def test_the_card_type_hierarchy_is_ordered_parent_before_child():
    """A container must never be weaker or smaller than what it contains.

    `[data-sc-sense-label]` opens a SECTION and owns every prose heading, inline
    label and example inside that sense -- yet it was set at 600/0.92em while
    `[data-sc-prose-heading]`, its own child, was 700/1.02em. The hierarchy was
    measurably INVERTED, and round 15 read it off the real host as the single
    highest-leverage change: "the top-level section header is weaker than a
    subordinate note header inside it".

    This asserts the DECLARED tiers, so a future tweak to one rule cannot silently
    re-invert them.
    """
    import re

    from bugd.styles import STYLES_CSS

    def declared(selector):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", STYLES_CSS)
        assert block, f"{selector} must have its own rule"
        body = block.group(1)
        size = re.search(r"font-size:\s*([0-9.]+)em", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        return (
            float(size.group(1)) if size else 1.0,
            int(weight.group(1)) if weight else 400,
        )

    sense_size, sense_weight = declared("[data-sc-sense-label]")
    head_size, head_weight = declared("[data-sc-prose-heading]")

    assert sense_size > head_size, (
        f"a sense label ({sense_size}em) must be larger than the prose heading "
        f"it contains ({head_size}em)"
    )
    assert sense_weight >= head_weight, (
        f"a sense label ({sense_weight}) must not be lighter than the prose "
        f"heading it contains ({head_weight})"
    )
    # A section header needs asymmetric space: generous above to detach from the
    # previous sense, tight below to bind to its own content.
    from conftest import resolve_space_tokens

    block = re.search(
        r"\[data-sc-sense-label\]\s*\{([^}]*)\}", resolve_space_tokens(STYLES_CSS)
    )
    top = re.search(r"margin-top:\s*([0-9.]+)em", block.group(1))
    bottom = re.search(r"margin-bottom:\s*([0-9.]+)em", block.group(1))
    assert top and bottom
    assert float(top.group(1)) > float(bottom.group(1)) * 2

    # The break between senses must be visible, not Yomitan's ~1.07:1 `#eee`.
    rule = re.search(
        r"\[data-sc-sense\] \+ \[data-sc-sense-label\]\s*\{([^}]*)\}", STYLES_CSS
    )
    assert rule, "the sense boundary needs its own rule"
    assert "--bugd-control-edge" in rule.group(1), (
        "the strongest structural break must not use the weakest colour available"
    )


def test_load_bearing_content_is_not_drawn_in_a_de_emphasis_token():
    """Primary content must not be dimmer than the text around it.

    `[data-sc-pattern]` -- the construction formula, the line a learner scans to
    answer "how do I build this sentence?" -- was drawn in `--bugd-muted`, the same
    token used for attribution and derivations. That made the most load-bearing
    content the dimmest text in the card, using the grey convention UIs reserve for
    disabled or placeholder text. Round 16 named the inversion as its single
    highest-impact change.

    Secondary status belongs in STRUCTURE (indent, rule), not in drained contrast.
    """
    import re

    from bugd.styles import STYLES_CSS

    DIM = ("--bugd-muted", "--bugd-quiet")

    def body_of(selector):
        # Anchored to line start: a role now ALSO appears in contextual overrides
        # such as `[data-sc-prose] div + [data-sc-prose-translation] { ... }`, and
        # an unanchored search would read that spacing-only block instead of the
        # role's own declarations and report a false "not quieted" defect.
        block = re.search(
            r"^" + re.escape(selector) + r"\s*\{([^}]*)\}", STYLES_CSS, re.M
        )
        assert block, f"{selector} must have its own rule"
        # Strip CSS comments: these rules explain WHY a token was removed, so a
        # naive substring search matches the rationale and reports a false defect.
        return re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)

    # Primary roles: never dimmed.
    for selector in ("[data-sc-pattern]", "[data-sc-prose-heading]", "[data-sc-sense-label]"):
        body = body_of(selector)
        for token in DIM:
            assert token not in body, f"{selector} is primary content and must not use {token}"

    pattern = body_of("[data-sc-pattern]")
    # Its subordination must be structural instead.
    assert re.search(r"padding-left:\s*[0-9.]+em", pattern), (
        "a pattern needs an indent to express subordination without dimming"
    )
    assert "border-left" in pattern, "a pattern needs its own rule"

    # Genuinely secondary roles KEEP their de-emphasis, so the contrast between the
    # two tiers is preserved rather than flattened.
    for selector in (
        "[data-sc-attribution]",
        "[data-sc-example-derivation]",
        "[data-sc-prose-translation]",
    ):
        body = body_of(selector)
        assert any(token in body for token in DIM), (
            f"{selector} is secondary and should stay quieter than primary content"
        )


def test_the_example_surface_is_actually_perceptible():
    """A fill present in the DOM but not to the eye is not a fill.

    `--bugd-example-well` was `rgba(127,127,127,0.06)`, which composites to
    rgb(247,247,247) on white -- 1.07:1 against its own backdrop, the same
    present-but-invisible failure the `#eee` border had. Rounds 15, 16 and 17 each
    reported the example surface as MISSING, while a DOM probe measured all 93
    example nodes carrying an identical fill. When independent reviews disagree
    with the DOM, the fill is too faint, not the reviews wrong.

    It must also stay BELOW the control fill: a reading region should never
    outweigh an interactive one.
    """
    import re

    from bugd.styles import STYLES_CSS

    def _composite(grey, alpha, surface):
        return tuple(round(g * alpha + s * (1 - alpha)) for g, s in zip(grey, surface))

    def _luminance(rgb):
        chan = []
        for value in rgb:
            v = value / 255
            chan.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

    def _contrast(a, b):
        la, lb = _luminance(a), _luminance(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    def token(name):
        match = re.search(
            rf"--{name}:\s*rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", STYLES_CSS
        )
        assert match, f"--{name} must be a literal rgba()"
        return (
            tuple(int(match.group(i)) for i in (1, 2, 3)),
            float(match.group(4)),
        )

    grey, alpha = token("bugd-example-well")
    _, control_alpha = token("bugd-well")

    for surface, name in (((255, 255, 255), "light"), ((30, 30, 30), "dark")):
        fill = _composite(grey, alpha, surface)
        ratio = _contrast(fill, surface)
        assert ratio >= 1.14, (
            f"the example surface composites to {fill} on the {name} background, "
            f"only {ratio:.2f}:1 -- three reviews read that as no surface at all"
        )
        # And it must stay a READING region, not shout like a control.
        assert ratio <= 1.4, f"the example surface is too loud on {name}: {ratio:.2f}:1"

    assert alpha < control_alpha, (
        f"the example fill ({alpha}) must stay below the control fill "
        f"({control_alpha}): a reading region must not outweigh a control"
    )


def test_the_vertical_spacing_scale_has_separable_steps_bound_to_one_job_each():
    """Vertical space must carry grouping information, not just exist.

    Defect 12, found by MEASURING the real host rather than by re-scoring.
    `harness/probe-prose-rhythm.mjs` walked every consecutive prose child pair at
    360px. Plain paragraph pairs were a perfectly uniform 7.69px, so the review's
    literal claim -- that some paragraphs fuse while neighbours are widely spaced
    -- was false. What it did prove is that seven distinct gap values collapsed
    into two colliding bands:

        new paragraph      7.69px
        label lead-in      6.92px   <- three different jobs within 0.8px
        translation tier   7.23px
        new example set   13.30px
        section heading   14.27px   <- a section no clearer than the next example

    Two independent reads of the same tile named it: "at least four or five
    unrelated vertical gap values with no shared scale... you can't tell new
    paragraph from same paragraph wrapped, or new group from continued group".

    This asserts the PROPERTY that was violated, so it fails for any future
    regression rather than only for the七 values seen that day:
      1. the scale exists and is ordered;
      2. consecutive steps are separated by >=1.5x, the point at which a step
         reads as a different KIND of break without conscious measurement;
      3. every vertical gap in prose comes FROM the scale, so a new ad-hoc
         literal cannot quietly reintroduce a colliding band.
    """
    import re

    from bugd.styles import STYLES_CSS

    card = re.search(r"\[data-sc-grammar-card\]\s*\{(.*?)\n\}", STYLES_CSS, re.S)
    assert card, "the card needs its token block"
    scale = {
        name: float(value)
        for name, value in re.findall(
            r"--bugd-space-([a-z]+):\s*([0-9.]+)em\s*;", card.group(1)
        )
    }
    assert set(scale) == {"tight", "para", "group", "section"}, (
        f"expected a four-step scale, got {sorted(scale)}"
    )

    # (1) ordered, and (2) each step a clear multiple of the one below it.
    ordered = ["tight", "para", "group", "section"]
    for lower, upper in zip(ordered, ordered[1:]):
        assert scale[upper] > scale[lower], (
            f"--bugd-space-{upper} ({scale[upper]}em) must exceed "
            f"--bugd-space-{lower} ({scale[lower]}em)"
        )
        ratio = scale[upper] / scale[lower]
        assert ratio >= 1.5, (
            f"--bugd-space-{upper}/{lower} is only {ratio:.2f}x: the two steps "
            "collapse into one perceptual band, which is the defect this scale "
            "exists to fix (measured 7.69 vs 6.92 vs 7.23px for three different "
            "jobs, and 13.3 vs 14.27px for a set gap vs a section heading)"
        )

    # (3) No ad-hoc vertical gap may survive in the prose/example rules. A literal
    # length here is exactly how the colliding bands appeared in the first place.
    scaled_roles = (
        "data-sc-prose-heading",
        "data-sc-prose-translation",
        "data-sc-example-label",
        "data-sc-sense-label",
        "data-sc-examples",
    )
    for role in scaled_roles:
        for block in re.findall(
            r"\[" + role + r"\][^{}]*\{([^}]*)\}", STYLES_CSS
        ):
            for prop, value in re.findall(
                r"(margin-top|margin-bottom):\s*([^;]+);", block
            ):
                if value.strip() == "0":
                    continue
                assert "--bugd-space-" in value, (
                    f"[{role}] declares {prop}: {value.strip()} as a literal; "
                    "vertical space must come from the shared scale so two "
                    "different semantic jobs cannot land in the same band"
                )

    # The paragraph rhythm and the inter-set gap must be DIFFERENT steps, or
    # proximity carries no grouping information inside an example run.
    para_rule = re.search(
        r"\[data-sc-prose\] div \+ div \{([^}]*)\}", STYLES_CSS
    )
    assert para_rule and "--bugd-space-para" in para_rule.group(1)
    set_gap = re.search(
        r":not\(\[data-sc-example-annotation\]\)\s*\{([^}]*)\}", STYLES_CSS
    )
    assert set_gap and "--bugd-space-group" in set_gap.group(1), (
        "a new example set must take the group step, not the paragraph step"
    )


def test_a_roles_own_spacing_step_is_not_overridden_by_the_paragraph_rhythm():
    """A declared step must WIN, not merely be declared.

    `[data-sc-prose] div + div` is specificity (0,1,2). A bare role selector such
    as `[data-sc-example-label]` is (0,1,0), so its `margin-top` LOSES to the
    paragraph rhythm and never renders. This is not hypothetical: after the
    four-step scale landed, `harness/probe-prose-rhythm.mjs` still measured the
    example label at 6.92px in the real host -- the para step resolved against the
    label's smaller 0.9em font -- instead of the group step it declares. Two
    independent reviews had already named that collision (paragraph 7.69px vs
    label lead-in 6.92px vs translation 7.23px: three jobs, one band).

    So for every role that declares a step DIFFERENT from the paragraph step,
    require a contextual `[data-sc-prose] div + [role]` override, which is (0,2,2)
    and therefore actually applies. Without this, a future role can declare a
    beautiful step that the cascade silently discards.
    """
    import re

    from bugd.styles import STYLES_CSS

    from conftest import resolve_space_tokens

    para = re.search(
        r"\[data-sc-prose\] div \+ div \{([^}]*)\}", STYLES_CSS
    )
    assert para, "the paragraph rhythm rule must exist"
    para_step = re.search(r"--bugd-space-([a-z]+)", para.group(1))
    assert para_step, "the paragraph rhythm must come from the scale"

    # Roles that live inside [data-sc-prose] as sibling divs and want their own step.
    for role, expected in (
        ("data-sc-prose-heading", "section"),
        ("data-sc-example-label", "group"),
        ("data-sc-prose-translation", "tight"),
    ):
        own = re.search(r"^\[" + role + r"\]\s*\{([^}]*)\}", STYLES_CSS, re.M)
        override = re.search(
            r"\[data-sc-prose\] div \+ \[" + role + r"\]\s*\{([^}]*)\}", STYLES_CSS
        )
        assert override, (
            f"[{role}] wants the {expected} step, but without a "
            f"`[data-sc-prose] div + [{role}]` override at (0,2,2) the "
            f"(0,1,2) paragraph rhythm wins and its step never renders"
        )
        step = re.search(r"--bugd-space-([a-z]+)", override.group(1))
        assert step and step.group(1) == expected, (
            f"[{role}] override should take the {expected} step, "
            f"got {step.group(1) if step else None}"
        )
        assert step.group(1) != para_step.group(1), (
            f"[{role}] takes the same step as a plain paragraph, so its "
            "override is pointless -- the whole reason it exists is that its "
            "break means something different"
        )
        # The role's own rule must not silently declare a conflicting margin-top.
        if own:
            own_margin = re.search(r"margin-top:\s*([^;]+);", own.group(1))
            if own_margin and "--bugd-space-" in own_margin.group(1):
                own_step = re.search(r"--bugd-space-([a-z]+)", own_margin.group(1))
                assert own_step.group(1) == expected, (
                    f"[{role}] declares the {own_step.group(1)} step in its own "
                    f"rule but the {expected} step in its override: one of them "
                    "is dead code and a reader cannot tell which applies"
                )

    # And the resolved numbers must still land in separable bands.
    css = resolve_space_tokens(STYLES_CSS)
    steps = {}
    for name in ("tight", "para", "group", "section"):
        m = re.search(r"--bugd-space-" + name + r":\s*([0-9.]+)em", css)
        assert m
        steps[name] = float(m.group(1))
    assert steps["group"] / steps["para"] >= 1.5, (
        "a group break must be a clear step over a paragraph break, or "
        "proximity carries no grouping information"
    )


def test_a_repeated_bracketed_classifier_does_not_break_an_example_run():
    """Defect 13: only the FIRST example in a run was boxed.

    edewakaru uses `【…】` two different ways. As a section heading it appears once
    (`【説明】`). As a per-example CLASSIFIER it repeats after every specimen. Since
    `_ends_example_run` treated any bracketed heading as a boundary, an interleaved
    run came out as one boxed example followed by plain unboxed prose:

        ［例］
        このバッグは若い女の子の間で人気があるようだ   inlineExample   <- boxed
        【複数の人の中での状態】                       proseHeading    <- closed run
        複数の人→若い女の子たち状態→人気               <none>
        OLの間で話題になっているカフェ                 <none>          <- NOT boxed

    Round 19 filed this three separate times on 間, all naming 絵でわかる日本語:
    "some get a shaded box with left rule while others are plain bold text ...
    for the same content role". Recurrence is the discriminator, measured over the
    whole source corpus: 31 example lines across 8 fields reclaimed, all edewakaru,
    with the three entries `verify_round10_fixes.py` guards left untouched.
    """
    from bugd.banks import _paragraphs, _recurring_bracketed_labels

    field = (
        "【説明】\n"
        "「〜間」は「〜の中で」という意味を表す文型です。\n"
        "［例］\n"
        "このバッグは若い女の子の間で人気があるようだ\n"
        "【複数の人の中での状態】\n"
        "複数の人→若い女の子たち状態→人気\n"
        "OLの間で話題になっているカフェ\n"
        "【複数の人の中での状態】\n"
        "複数の人→OLたち状態→話題になっている\n"
        "あのアニメは小学生の間で大人気なんだって\n"
        "【複数の人の中での状態】\n"
        "複数の人→小学生たち状態→大人気\n"
    )
    lines = field.split("\n")

    # The classifier recurs; the genuine section heading does not.
    recurring = _recurring_bracketed_labels(lines)
    assert "【複数の人の中での状態】" in recurring
    assert "【説明】" not in recurring, (
        "a heading that appears once must stay a section boundary"
    )

    nodes = [n for n in _paragraphs(field) if isinstance(n, dict)]
    roles = [frozenset(n.get("data") or {}) for n in nodes]

    # Every one of the three specimens must be boxed, not just the first.
    specimens = [
        n for n, r in zip(nodes, roles)
        if "inlineExample" in r and "exampleAnnotation" not in r
        and isinstance(n.get("content"), str)
        and not n["content"].startswith("→")
        and not n["content"].startswith("複数")
    ]
    texts = [n["content"] for n in specimens]
    for want in (
        "このバッグは若い女の子の間で人気があるようだ",
        "OLの間で話題になっているカフェ",
        "あのアニメは小学生の間で大人気なんだって",
    ):
        assert want in texts, (
            f"{want!r} is example content in the same run and must carry the "
            "example role; without it the line renders as plain prose while its "
            "siblings are boxed"
        )

    # No line inside the run may be left unroled -- that is the visible defect.
    seen_label = False
    for node, role in zip(nodes, roles):
        if "exampleLabel" in role:
            seen_label = True
            continue
        if not seen_label:
            continue
        assert role, (
            f"{node.get('content')!r} sits inside an example run with NO role, so "
            "it renders as plain prose beside boxed siblings"
        )

    # The classifier must NOT also be a section heading: it would be drawn as a
    # landmark inside the example box and carry three conflicting roles at once.
    for node, role in zip(nodes, roles):
        if node.get("content") == "【複数の人の中での状態】":
            assert "exampleAnnotation" in role and "inlineExample" in role
            assert "proseHeading" not in role, (
                "a classifier inside a run is an annotation of the specimen "
                "above it, not a section heading"
            )

    # A heading that appears ONCE must still close the run (round-10 guarantee).
    once = (
        "［例］\n"
        "①彼女は授業の間、ずっと寝ていた\n"
        "［説明］\n"
        "「〜間」は期間を表します。\n"
    )
    once_nodes = [n for n in _paragraphs(once) if isinstance(n, dict)]
    explanation = [n for n in once_nodes if n.get("content") == "［説明］"]
    assert explanation, "the single-occurrence heading must still be emitted"
    assert "inlineExample" not in (explanation[0].get("data") or {}), (
        "a one-off section heading must still END the run, or it is drawn "
        "inside the tinted example block"
    )


def test_a_classifier_counts_as_recurring_at_exactly_two_occurrences():
    """Pin the recurrence threshold at 2, not 3.

    The defect-13 fixture happens to repeat its classifier three times, so a
    mutation loosening the threshold from `n > 1` to `n > 2` SURVIVED the main
    test. Two occurrences is the real boundary: one means a section heading,
    two already means the producer is classifying per example, and a two-specimen
    run is the commonest shape in the corpus.
    """
    from bugd.banks import _paragraphs, _recurring_bracketed_labels

    field = (
        "［例］\n"
        "このバッグは若い女の子の間で人気があるようだ\n"
        "【複数の人の中での状態】\n"
        "OLの間で話題になっているカフェ\n"
        "【複数の人の中での状態】\n"
    )
    lines = field.split("\n")
    assert lines.count("【複数の人の中での状態】") == 2, "fixture must have exactly two"
    assert "【複数の人の中での状態】" in _recurring_bracketed_labels(lines), (
        "two occurrences already mean a per-example classifier: at a threshold of "
        "three, a two-specimen run still loses the box on its second example"
    )

    nodes = [n for n in _paragraphs(field) if isinstance(n, dict)]
    texts = {
        n["content"]: frozenset(n.get("data") or {})
        for n in nodes
        if isinstance(n.get("content"), str)
    }
    assert "inlineExample" in texts["OLの間で話題になっているカフェ"], (
        "the SECOND specimen must still be boxed when the classifier appears twice"
    )


def test_both_example_roles_hang_their_wrapped_lines():
    """Defect 14: only the IN-PROSE example role had a hanging indent.

    An earlier round gave `[data-sc-inline-example]` `padding-left` +
    negative `text-indent` so a wrapped continuation tucks under its own first
    line. The STANDALONE `[data-sc-example]` list never got the same treatment,
    and `harness/probe-hanging-indent.mjs` measured the consequence in the real
    host at 360px:

        [data-sc-example]        text-indent: 0px   -> 56/56 wrapped FLUSH,
                                                      16 continuations <= 3 glyphs
        [data-sc-inline-example] text-indent: -15.4px -> 17/17 tucked correctly

    A bare `わ` / `よ！` / `た` starting at the same x as a new sentence reads as a
    new example, so line-initial position carried no information. The two roles had
    to be measured SEPARATELY -- one combined "examples" verdict would have been
    wrong whichever way it fell.

    This asserts the invariant rather than the two numbers: wherever the producer
    put an example, a wrap tucks to the same depth.
    """
    import re

    from bugd.styles import STYLES_CSS

    def hanging(selector):
        block = re.search(
            r"^\[" + selector + r"\]\s*\{([^}]*)\}", STYLES_CSS, re.M
        )
        assert block, f"[{selector}] must have its own rule"
        body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
        pad = re.search(r"padding-left:\s*([0-9.]+)em", body)
        indent = re.search(r"text-indent:\s*-([0-9.]+)em", body)
        assert pad, f"[{selector}] needs a left pad to hang into"
        assert indent, (
            f"[{selector}] declares no negative text-indent, so a wrapped line "
            "starts at the same x as a new one and reads as a new example"
        )
        return float(pad.group(1)), float(indent.group(1))

    standalone = hanging("data-sc-example")
    in_prose = hanging("data-sc-inline-example")

    # The outdent must be smaller than the pad, or line 1 escapes the box.
    for name, (pad, indent) in (("data-sc-example", standalone),
                                ("data-sc-inline-example", in_prose)):
        assert indent < pad, (
            f"[{name}] outdents {indent}em from a {pad}em pad, which pulls the "
            "first line outside its own tinted block"
        )

    # Both example kinds must hang to the SAME depth: a reader should not have to
    # learn two indent languages depending on which field the producer used.
    assert standalone == in_prose, (
        f"standalone examples hang {standalone} but in-prose examples hang "
        f"{in_prose}; the same content role must indent identically"
    )

    # A negative text-indent INHERITS. The nested English translation is a sibling
    # block, not a continuation, so it must reset -- otherwise its first line is
    # pulled left of the Japanese it translates.
    en = re.search(r"^\[data-sc-en\]\s*\{([^}]*)\}", STYLES_CSS, re.M)
    assert en, "[data-sc-en] must have its own rule"
    en_body = re.sub(r"/\*.*?\*/", "", en.group(1), flags=re.S)
    assert re.search(r"text-indent:\s*0", en_body), (
        "[data-sc-en] must reset the inherited negative text-indent, or the "
        "translation starts outside the example it belongs to"
    )


def test_a_control_surface_is_perceptibly_different_from_a_reading_surface():
    """Defect 15: ordering two alphas is not making them distinguishable.

    An earlier round asserted `--bugd-example-well < --bugd-well` so a reading
    region could never outweigh a control. That assertion passed at 0.13 vs 0.14 --
    and `probe_control_vs_region.py` composited both against Yomitan's real
    surfaces to find the control at rgb(237,237,237) and the region at
    rgb(238,238,238): ONE unit apart, 1.0116:1 light and 1.0134:1 dark.

    That is the missing explanation for a recurring report. Rounds 15, 17 and 20
    each independently called one of these surfaces absent while the DOM insisted
    it was there; round 20's must-fix read "looks like a plain heading rather than
    an interactive disclosure control". The rows were provably CONSISTENT (8 rows,
    1 computed style), so consistency was never the defect -- a control simply had
    no perceptible surface of its own.

    An ordering test cannot catch that, so this one does real WCAG compositing and
    requires a MARGIN, not just an inequality.
    """
    import re

    from bugd.styles import STYLES_CSS

    def srgb_to_lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def luminance(rgb):
        r, g, b = (srgb_to_lin(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast(a, b):
        la, lb = luminance(a), luminance(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    def composite(grey, alpha, back):
        return tuple(grey * alpha + b * (1 - alpha) for b in back)

    def token(name):
        m = re.search(
            rf"{name}:\s*rgba\(\s*(\d+),\s*\d+,\s*\d+,\s*([0-9.]+)\s*\)", STYLES_CSS
        )
        assert m, f"{name} must be declared as an rgba grey"
        return int(m.group(1)), float(m.group(2))

    control = token("--bugd-well")
    region = token("--bugd-example-well")
    hover = token("--bugd-well-hover")

    # The original ordering guarantee still holds.
    assert region[1] < control[1], (
        "a reading region must not be louder than a control"
    )
    # Hover must still lift the control.
    assert hover[1] > control[1], "the hover state must be louder than rest"

    for theme, back in (("light", (255, 255, 255)), ("dark", (30, 30, 30))):
        ctl = composite(*control, back)
        reg = composite(*region, back)

        # Each surface must be perceptible against the page at all.
        assert contrast(ctl, back) >= 1.2, (
            f"[{theme}] the control fill is {contrast(ctl, back):.3f}:1 against "
            "the page: present in the DOM, absent to the eye"
        )

        # And -- the point of this test -- a control must be perceptibly NOT a
        # reading region. 1.05:1 is a generous floor; 1.0116:1 shipped.
        separation = contrast(ctl, reg)
        assert separation >= 1.05, (
            f"[{theme}] a disclosure control and a reading region differ by only "
            f"{separation:.4f}:1, so a control cannot be told from a passage of "
            "text by its surface. Ordering the alphas is not enough."
        )

        # But a quiet well must not become a loud button either.
        assert contrast(ctl, back) <= 2.0, (
            f"[{theme}] the control fill is {contrast(ctl, back):.3f}:1 against "
            "the page, which is a button, not a quiet disclosure well"
        )


def test_the_gap_between_example_boxes_is_at_least_their_internal_padding():
    """Defect 16: boxes bound more tightly to each other than to their own text.

    A tinted box only reads as one unit if the space OUTSIDE it exceeds the space
    inside it; otherwise Gestalt proximity groups across the boundary and N
    specimens read as one continuously banded slab.
    `harness/probe-example-box-model.mjs` measured the shipped card in the real
    host at 360px: inner padding 9.59px top / up to 10.59px bottom against a 7px
    inter-box gap. Round 21 reported exactly that ("blocks fuse into one
    continuously banded slab").

    The same probe REFUTED the other half of that report -- inner top padding had
    a spread of exactly 0 across all 66 boxes, so "internal padding is
    inconsistent" was false -- which is why the fix is separation only and not a
    padding rewrite.
    """
    import re

    from bugd.styles import STYLES_CSS

    from conftest import resolve_space_tokens

    css = resolve_space_tokens(STYLES_CSS)
    block = re.search(r"^\[data-sc-example\]\s*\{([^}]*)\}", css, re.M)
    assert block, "[data-sc-example] must have its own rule"
    body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)

    gap = re.search(r"margin:\s*0\s+0\s+([0-9.]+)em", body)
    assert gap, "an example box needs a bottom margin separating it from the next"
    # Read BOTH padding values. A mutation that grew only the horizontal pad
    # survived a version of this test that matched the first number, because
    # `padding: 0.4em 1.4em` still reported 0.4em.
    pad = re.search(r"padding:\s*([0-9.]+)em(?:\s+([0-9.]+)em)?", body)
    assert pad, "an example box needs its own padding"

    gap_em = float(gap.group(1))
    pad_values = [float(v) for v in pad.groups() if v is not None]
    pad_em = max(pad_values)
    # The box's padding applies at every edge, so two adjacent boxes put interior
    # space on both sides of the single inter-box gap. The gap must at least match
    # the largest interior pad, or the boundary is the tightest space around.
    assert gap_em >= pad_em, (
        f"boxes are separated by {gap_em}em but padded up to {pad_em}em inside "
        f"(padding: {pad_values}), so each box is bound more tightly to its "
        "neighbour than to its own text and the run reads as one banded region "
        "instead of N specimens"
    )

    # And the separation must come from the shared scale, not a private value.
    # Read the RAW stylesheet here: `css` has already had its tokens resolved to
    # numbers, so searching it for a token name can never match.
    raw = re.search(r"^\[data-sc-example\]\s*\{([^}]*)\}", STYLES_CSS, re.M)
    assert raw
    raw_margin = re.search(r"margin:\s*0\s+0\s+([^;]+);", raw.group(1))
    assert raw_margin and "--bugd-space-" in raw_margin.group(1), (
        "box separation must be metered by the shared spacing scale, or the card "
        "carries two competing rhythms"
    )


def test_de_emphasis_tokens_clear_wcag_against_the_cards_own_surfaces():
    """Defect 17: secondary text failed WCAG on the surfaces the card itself paints.

    `--bugd-quiet` used to resolve to Yomitan's `#777`, which is fine on white but
    not on a card that paints translucent wells under its secondary text.
    `harness/probe-text-contrast.mjs` composited every ancestor background and
    measured SIX roles below their floor at 780px light -- worst 3.87:1 for the
    English translation, which is the payload for a learner. Raising the control
    fill for defect 15 had made `source-name` worse, at 4.36:1.

    A "colour versus page background" assertion cannot catch this, so this test
    composites the card's own fills the same way a browser does and checks the
    de-emphasis tokens against the WORST surface they can land on, in both themes.

    Deliberately checks the DERIVATION, not a hard-coded hex: the tokens are
    `color-mix` toward the background so they track any Yomitan theme.
    """
    import re

    from bugd.styles import STYLES_CSS

    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(rgb):
        r, g, b = (lin(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast(a, b):
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    def mix(fg, bg, pct):
        """CSS color-mix(in srgb, fg pct%, bg) -- linear in sRGB space."""
        return tuple(f * pct + b * (1 - pct) for f, b in zip(fg, bg))

    def token_pct(name):
        m = re.search(
            rf"{name}:\s*color-mix\(in srgb,\s*var\(--text-color[^)]*\)\s*(\d+)%",
            STYLES_CSS,
        )
        assert m, (
            f"{name} must be derived with color-mix from Yomitan's --text-color so "
            "it tracks the theme instead of hard-coding a light-theme grey"
        )
        return int(m.group(1)) / 100.0

    def alpha(name):
        m = re.search(
            rf"{name}:\s*rgba\(\s*(\d+),\s*\d+,\s*\d+,\s*([0-9.]+)\s*\)", STYLES_CSS
        )
        assert m, f"{name} must be an rgba grey"
        return int(m.group(1)), float(m.group(2))

    muted_pct, quiet_pct = token_pct("--bugd-muted"), token_pct("--bugd-quiet")
    well = alpha("--bugd-well")
    example_well = alpha("--bugd-example-well")

    # Yomitan's real light/dark text and background pairs (ext/css/display.css).
    for theme, text, page in (
        ("light", (0, 0, 0), (255, 255, 255)),
        ("dark", (245, 245, 245), (30, 30, 30)),
    ):
        # Every surface a de-emphasised role can actually sit on.
        surfaces = {
            "page": page,
            "example well": tuple(
                example_well[0] * example_well[1] + p * (1 - example_well[1]) for p in page
            ),
            "control well": tuple(
                well[0] * well[1] + p * (1 - well[1]) for p in page
            ),
        }
        for token_name, pct in (("--bugd-muted", muted_pct), ("--bugd-quiet", quiet_pct)):
            colour = mix(text, page, pct)
            for surface_name, surface in surfaces.items():
                ratio = contrast(colour, surface)
                assert ratio >= 4.5, (
                    f"[{theme}] {token_name} is {ratio:.2f}:1 on the {surface_name}, "
                    f"below the 4.5:1 floor for body text. The card's own fill is "
                    f"the backdrop that eats the margin, so a check against the "
                    f"page background alone would miss this."
                )
            # It must still be QUIETER than primary text, or de-emphasis is a lie.
            assert contrast(colour, page) < contrast(text, page), (
                f"[{theme}] {token_name} is not quieter than primary text"
            )

    # And muted must stay stronger than quiet: two tiers, not one.
    assert muted_pct > quiet_pct, (
        "--bugd-muted must be stronger than --bugd-quiet, or the two "
        "de-emphasis tiers collapse into one"
    )


def test_a_section_landmark_has_a_perceptible_size_step_over_body_text():
    """Defect 18: bold alone is not a size step.

    `harness/probe-hierarchy.mjs` measured the prose heading at 14.28px against
    14px body -- 1.02x. That cleared the existing `>= 1.0em` assertion while being
    invisible as a size difference, so the heading read as inline bold and the
    divider hairline carried the whole "new section starts here" signal. Round 23:
    "a sense heading that opens a whole new grammatical pattern is doing the work
    of an h3 with the visual authority of inline bold".

    1.1x is the floor at which a size change registers as a different KIND of text
    rather than as an accident. This also re-checks the containment ordering, since
    raising a nested landmark is exactly how a hierarchy gets inverted.
    """
    import re

    from bugd.styles import STYLES_CSS

    def size_of(selector):
        block = re.search(r"^\[" + selector + r"\]\s*\{([^}]*)\}", STYLES_CSS, re.M)
        assert block, f"[{selector}] must have its own rule"
        body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
        m = re.search(r"font-size:\s*([0-9.]+)em", body)
        assert m, f"[{selector}] must declare a font-size"
        return float(m.group(1))

    heading = size_of("data-sc-prose-heading")
    sense = size_of("data-sc-sense-label")

    assert heading >= 1.1, (
        f"a prose heading at {heading}em is only {heading:.2f}x body text, below "
        "the ~1.1x at which a size step reads as a different kind of text; bold "
        "alone leaves the boundary rule carrying the entire section signal"
    )
    # The container must keep a real step over the landmark it contains.
    assert sense / heading >= 1.1, (
        f"a sense label ({sense}em) is only {sense / heading:.2f}x the prose "
        f"heading it contains ({heading}em); raising the nested landmark must not "
        "flatten the level above it"
    )


def test_a_bracketed_term_the_producer_wrapped_a_sentence_around_is_not_a_heading():
    """Defect 19: one sentence became a landmark plus an orphaned particle.

    `_PROSE_HEADING` matches any wholly-bracketed short line, but edewakaru also
    writes bracketed TERMS inline and wraps the sentence around them, so a single
    sentence arrives as four lines:

        【複数の人の中での状態】      -> promoted to a section landmark
        や                           -> orphaned connector under a big bold heading
        【〜と〜の関係の中のこと】
        などを言いたい時に使います😊  -> orphaned sentence tail

    Round 24 filed it as "only isolated connector words appear with large
    surrounding empty space, as if list content is missing". Raising landmark size
    for defect 18 exposed the mismatch rather than causing it.

    Discriminator: what FOLLOWS. A real heading is followed by a self-contained
    sentence; an inline term is followed by a line that cannot open one. Measured
    over the whole source corpus this reclassifies 11 of 1,523 bracketed
    headings, all genuine `【…】や【…】など…` enumerations, so a heading test must
    still pass for the other 1,512.
    """
    from bugd.banks import _paragraphs

    wrapped = (
        "「〜間」は「〜の中で」という意味を表す文型です。\n"
        "【複数の人の中での状態】\n"
        "や\n"
        "【〜と〜の関係の中のこと】\n"
        "などを言いたい時に使います\n"
    )
    nodes = [n for n in _paragraphs(wrapped) if isinstance(n, dict)]

    def role_of(text):
        for n in nodes:
            content = n.get("content")
            if content == text:
                return frozenset(n.get("data") or {})
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("content") == text:
                        return frozenset(c.get("data") or {})
        raise AssertionError(f"{text!r} not emitted")

    for term in ("【複数の人の中での状態】", "【〜と〜の関係の中のこと】"):
        role = role_of(term)
        assert "proseHeading" not in role, (
            f"{term} is a term inside a running sentence -- the next line is a "
            "bare connector that cannot open a sentence -- so promoting it to a "
            "section landmark orphans that connector under a big bold heading"
        )
        assert "proseLabel" in role, (
            f"{term} should be emphasised inline so the sentence reads as one unit"
        )

    # A genuine one-off heading, followed by a self-contained sentence, must STILL
    # be a landmark. Without this the fix would flatten 1,512 real headings.
    ordinary = (
        "【説明】\n"
        "「〜間」は期間を表す文型です。\n"
        "【注意】\n"
        "「〜間に」とは意味が違います。\n"
    )
    ordinary_nodes = [n for n in _paragraphs(ordinary) if isinstance(n, dict)]
    for heading in ("【説明】", "【注意】"):
        matches = [n for n in ordinary_nodes if n.get("content") == heading]
        assert matches, f"{heading} must be emitted"
        assert "proseHeading" in (matches[0].get("data") or {}), (
            f"{heading} is followed by a self-contained sentence, so it is a real "
            "section heading and must keep its landmark role"
        )
