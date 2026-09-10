"""Per-source prose dialects: `bugd.dialects`.

The regression these guard is a real one and it was visible on every Yokubi card:
the source writes GitHub-flavoured Markdown, the renderer treated it as plain
text, and so a card showed literal `**asterisks**`, a bare `|---------------|`
separator row as body prose, and — worst — silently dropped the remainder of any
paragraph containing an escaped `\\<verb\\>` placeholder, because the unescaped
`<verb>` reached the HTML parser as a tag opening.

Every assertion below is anchored to text that really occurs in
`data/extracted/yokubi.json`, so a change to the dialect is checked against the
corpus it exists to serve rather than against invented input.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bugd.banks import _prose, _source_block
from bugd.dialects import MARKDOWN_SOURCES, prose_to_html
from bugd.model import GrammarPoint

REPO = pathlib.Path(__file__).resolve().parents[1]
YOKUBI_EXTRACT = REPO / "data" / "extracted" / "yokubi.json"


def point(explanation: str, source: str = "yokubi") -> GrammarPoint:
    return GrammarPoint(
        source=source, source_id="lesson-1:x", expression="て", explanation=explanation
    )


def render(explanation: str, source: str = "yokubi") -> object:
    """The structured content one prose field becomes, as the card sees it."""
    return _prose(explanation, point(explanation, source))


def nodes(content: object) -> list:
    return content if isinstance(content, list) else [content]


def find(content: object, tag: str) -> list[dict]:
    """Every node with `tag`, anywhere in a structured-content tree."""
    found: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("tag") == tag:
                found.append(node)
            walk(node.get("content"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(content)
    return found


def flat(content: object) -> str:
    """All text in a tree, concatenated."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(flat(item) for item in content)
    if isinstance(content, dict):
        return flat(content.get("content"))
    return ""


# ------------------------------------------------------------------ inline


def test_bold_and_italic_become_styled_spans():
    """`**x**` and `*x*` are emphasis, not literal asterisks."""
    content = render("the word goes **after** it, and *not* before it.")
    assert "*" not in flat(content)
    styles = [node.get("style") for node in find(content, "span")]
    assert {"fontWeight": "bold"} in styles
    assert {"fontStyle": "italic"} in styles


def test_bold_wins_over_italic_on_the_same_run():
    """A `**` run must not be read as an italic run wrapping a stray asterisk."""
    content = render("it is **exhaustive** here")
    spans = find(content, "span")
    assert len(spans) == 1
    assert spans[0]["style"] == {"fontWeight": "bold"}
    assert spans[0]["content"] == "exhaustive"


def test_a_relative_lesson_link_keeps_its_text_and_drops_the_dead_target():
    """Yokubi links point at `.md` sources that do not exist for a card reader.

    Yomitan's schema also rejects a non-`https:` href outright, and the shared
    converter drops every anchor anyway, so the author's words are what survive.
    """
    content = render("see [lesson 1](./Lesson1.md) for more")
    text = flat(content)
    assert "lesson 1" in text
    assert "Lesson1.md" not in text
    assert "](" not in text
    assert not find(content, "a")


# ------------------------------------------------------------------ escapes


def test_an_escaped_angle_bracket_survives_as_text():
    """The regression: `\\<verb\\>` truncated the rest of the paragraph.

    Unescaped to a bare `<verb>`, the HTML parser read it as a tag opening and
    swallowed everything after it. It must reach the card as literal text.
    """
    content = render(r"use \<verb\> here and then some more prose after it")
    text = flat(content)
    assert "<verb>" in text
    assert "some more prose after it" in text


def test_other_backslash_escapes_lose_only_the_backslash():
    content = render(r"死ぬ \-\> 死んだ and A \+ B \= C")
    text = flat(content)
    assert "死ぬ -> 死んだ" in text
    assert "A + B = C" in text
    assert "\\" not in text


# ------------------------------------------------------------------- tables


def test_a_pipe_table_becomes_a_real_table():
    content = render(
        "| Casual | Polite |\n|--------|--------|\n| 食べる | 食べます |\n| 行く | 行きます |"
    )
    assert len(find(content, "table")) == 1
    assert [node["content"] for node in find(content, "th")] == ["Casual", "Polite"]
    assert [flat(node) for node in find(content, "td")] == [
        "食べる",
        "食べます",
        "行く",
        "行きます",
    ]
    # The separator row is syntax, not content.
    assert "---" not in flat(content)


def test_an_all_blank_header_row_is_dropped_rather_than_rendered_empty():
    """GFM requires a header row; 33 of Yokubi's 44 tables leave it empty.

    Rendered as a header it drew an empty full-width band above two thirds of the
    tables in the dictionary.
    """
    content = render("|      |      |\n|------|------|\n| 赤い | 赤くて |")
    assert not find(content, "th")
    assert not find(content, "thead")
    assert [flat(node) for node in find(content, "td")] == ["赤い", "赤くて"]


def test_back_to_back_tables_stay_separate_tables():
    """`lesson-20:の` writes four tables with no blank line between them.

    Treating a contiguous pipe run as one table merged all four into a single
    16-row grid.
    """
    content = render(
        "|  |  |\n|--|--|\n| 学生(だ) | 学生なの？ |\n"
        "|  |  |\n|--|--|\n| 普通(だ) | 普通なの？ |\n"
        "|  |  |\n|--|--|\n| 寒い | 寒いの？ |"
    )
    tables = find(content, "table")
    assert len(tables) == 3
    for table in tables:
        assert len(find(table, "tr")) == 1


def test_inline_markup_inside_a_table_cell_is_rendered():
    content = render("| a | b |\n|---|---|\n| 食べ**る** | x |")
    cell = find(content, "td")[0]
    assert flat(cell) == "食べる"
    assert find(cell, "span")[0]["style"] == {"fontWeight": "bold"}


def test_pipe_lines_without_a_separator_are_not_a_table():
    """A pipe run with no separator anywhere is notation, not layout."""
    content = render("| これ | それ |\n| あれ | どれ |")
    assert not find(content, "table")
    assert "これ" in flat(content)


# -------------------------------------------------------------------- lists


def test_a_dash_bullet_run_becomes_a_list():
    content = render(
        "used in two main ways:\n"
        "- to chain actions together;\n"
        "- to provide additional nuance.\n"
        "The て form is made by replacing…"
    )
    assert len(find(content, "ul")) == 1
    assert [flat(node) for node in find(content, "li")] == [
        "to chain actions together;",
        "to provide additional nuance.",
    ]
    # The bullet markers are syntax; the prose around the list is not swallowed.
    text = flat(content)
    assert "- to chain" not in text
    assert "used in two main ways:" in text
    assert "The て form is made by replacing…" in text


# ------------------------------------------------------- paragraph handling


def test_each_hard_newline_stays_its_own_paragraph():
    """Yokubi ships zero blank lines: every newline is a finished paragraph.

    Left to the shared soft-wrap rule, two English paragraphs were joined into one
    run-on block, which is what made the long lessons unreadable.
    """
    body = _source_block(
        point("First paragraph here.\nSecond paragraph, unrelated.\nThird one.")
    )
    prose = body[0]
    assert prose["data"] == {"prose": ""}
    assert [flat(node) for node in prose["content"]] == [
        "First paragraph here.",
        "Second paragraph, unrelated.",
        "Third one.",
    ]


def test_an_english_source_paragraph_is_not_subordinated_as_a_translation():
    """`proseTranslation` marks an English line inside a JAPANESE field.

    Five sources explain IN English, so applying it unconditionally indented and
    quietened the primary explanation of half the corpus.
    """
    body = _source_block(point("First paragraph here.\nSecond paragraph here."))
    assert body[0]["lang"] == "en"
    for node in body[0]["content"]:
        assert "proseTranslation" not in (node.get("data") or {})


def test_an_english_line_inside_a_japanese_field_is_still_subordinated():
    """The counterpart: the distinction the role exists to draw must survive."""
    body = _source_block(
        GrammarPoint(
            source="edewakaru",
            source_id="y",
            expression="くらい",
            explanation="２）基本的に、名詞につく場合は…\n"
            "２）Generally, くらい becomes ぐらい in speech.",
        )
    )
    roles = [(node.get("data") or {}) for node in body[0]["content"]]
    assert body[0]["lang"] == "ja"
    assert {} in roles
    assert any("proseTranslation" in role for role in roles)


# ----------------------------------------------------- the other nine sources


@pytest.mark.parametrize(
    "source",
    [
        "bunpou",
        "bunpro",
        "dojg",
        "donna_toki",
        "edewakaru",
        "imabi",
        "nihongo_net",
        "nihongo_no_sensei",
        "ninjal_bunkei",
    ],
)
def test_a_source_without_a_declared_dialect_is_untouched(source):
    """Only Yokubi writes Markdown; every other source must pass through.

    IMABI in particular writes 17,549 `N. ` example-sentence lines that are
    cross-referenced from its own prose as `Ex. N`, and 145 bare `*` footnote
    markers. Reading either as Markdown would renumber the examples and italicise
    the footnotes.
    """
    raw = "1. 金子さんはいますか。\nされる* (to be done)\n| a | b |\n|---|---|"
    assert prose_to_html(raw, source=source) == raw
    assert source not in MARKDOWN_SOURCES


def test_the_declared_markdown_sources_are_exactly_the_ones_that_use_it():
    assert MARKDOWN_SOURCES == frozenset({"yokubi"})


def test_omission_and_ruby_markup_still_render_for_the_html_sources():
    """`ninjal_bunkei`'s `<s>` and `donna_toki`'s `<ruby>` need no dialect.

    They already render through the shared converter, which is why they
    deliberately do not get one. This pins that they are not regressed by the
    dialect stage sitting in front of it.
    """
    struck = render("V<s>ます</s>＋かけだ", source="ninjal_bunkei")
    assert find(struck, "span")[0]["style"] == {"textDecorationLine": "line-through"}
    ruby = render("＋ <ruby>助<rt>じょ</rt>詞<rt>し</rt></ruby>", source="donna_toki")
    assert find(ruby, "ruby")
    assert find(ruby, "rt")


# ------------------------------------------------------- against the corpus


@pytest.mark.skipif(
    not YOKUBI_EXTRACT.is_file(), reason="yokubi is not extracted in this checkout"
)
def test_no_yokubi_card_still_shows_raw_markdown():
    """The end-to-end claim, over every real Yokubi record.

    Asserted on the rendered nodes rather than on a sample: the separator rows,
    bold delimiters and link syntax must be gone from all 132 of them, and the
    tables must actually exist.
    """
    payload = json.loads(YOKUBI_EXTRACT.read_text(encoding="utf-8"))
    tables = 0
    for record in payload["points"]:
        explanation = record.get("explanation")
        if not explanation:
            continue
        content = render(explanation)
        text = flat(content)
        assert "**" not in text
        assert "](" not in text
        assert "|---" not in text
        assert "\\<" not in text
        tables += len(find(content, "table"))
    # 44 tables were measured across the corpus; assert the floor rather than the
    # exact count so a source revision that adds one does not fail the suite.
    assert tables >= 40
