"""Per-source prose markup dialects.

Every producer writes its prose in its own notation, and the notation is part of
the content: a table is a table because the author laid it out as one. This module
is the ONE place that knows which notation a given source writes, and it converts
that notation into the HTML subset `bugd.richtext` already understands. The bank
generator therefore stays source-agnostic — it asks for the dialect of a source
and renders whatever comes back.

Why HTML as the intermediate rather than structured content directly: `richtext`
already maps `<strong>`/`<em>` onto `span` + the only two font styles Yomitan's
schema allows, and `<table>`/`<tr>`/`<th>`/`<td>`/`<ul>`/`<li>` are in its allowed
tag set verbatim. Emitting HTML reuses that mapping (and its schema conformance)
instead of growing a second node builder that could drift from it.

## What each source actually writes

Measured over the whole extracted corpus (7,896 points, all ten sources), the
prose fields (`explanation`, `nuance`, `notes`) divide into exactly two dialects:

* **`yokubi` writes GitHub-flavoured Markdown.** 44 pipe tables with `|---|`
  separator rows, 180 `**bold**` runs, 28 `*italic*` runs, 48 `- ` bullets, 26
  `[text](./LessonN.md)` links, and 149 backslash escapes (`\\>` 70, `\\<` 40,
  `\\-` 30, `\\+` 8, `\\=` 1). None of it rendered: a card showed literal
  asterisks, a `|---------------|` separator as body text, and — because an
  escaped `\\<verb\\>` placeholder reached the HTML parser as a tag opening — the
  rest of that paragraph was silently swallowed.

* **Every other source writes plain text plus, in two cases, real HTML** —
  `ninjal_bunkei`'s `<s>ます</s>` omission markers (526 tags, including 2
  malformed `</s/>` closers) and `donna_toki`'s `<ruby>`/`<rt>` furigana (32
  tags). Both already render correctly through `richtext.html_to_content`, so
  they need no dialect of their own and deliberately do not get one.

  Their other conventions are structural but not markup, and are already handled
  downstream: `【…】` section headings and `→` paraphrase lines by
  `banks._prose_paragraph`, `①②③` / `１）２）` list breaks by
  `richtext._LIST_BREAK`, and the hard line breaks that sources leave behind when
  an inline highlight is stripped (92.3% of `edewakaru`'s single newlines fall
  mid-sentence) by `richtext._join_soft_break`, which rejoins them
  script-awarely. Re-handling any of that here would double-apply it.

Markdown constructs `yokubi` does NOT use are deliberately not implemented, so
this module cannot claim coverage it has no evidence for: zero ATX headings, zero
ordered lists, zero backtick code spans, zero `_underscore_` emphasis, zero
`~~strikethrough~~`, zero bare `&`, zero nested lists (maximum bullet depth is 1).

## Two things that are load-bearing here

**`yokubi` has no blank lines at all**, and its median prose line is 138
characters. Every single `\\n` it writes is a hard block break — a finished
paragraph, a table row, or a bullet. `richtext._join_soft_break` resolves a lone
newline by script and punctuation, which is right for the Japanese sources that
hard-wrap mid-sentence but would glue two of `yokubi`'s English paragraphs
together. So paragraph breaks are doubled into blank lines before handing the
text over, which is unambiguous precisely because the source ships none.

**A pipe-line run can hold several tables back to back.** `lesson-20:の` writes
four two-column tables with no blank line between them. Splitting a run on
"contiguous pipe lines" would merge all four into one 16-row table, so the run is
split at *every* separator row instead.
"""

from __future__ import annotations

import re

#: Sources whose prose is GitHub-flavoured Markdown. Declared explicitly, not
#: sniffed: a heuristic that guessed "this looks like Markdown" would fire on the
#: `｜`-delimited notation and bare `*` footnote markers other producers write,
#: and the guess would change with the corpus. An unlisted source keeps the plain
#: handling it has today.
MARKDOWN_SOURCES = frozenset({"yokubi"})

#: Backslash escapes `yokubi` uses. `<` and `>` become HTML entities rather than
#: bare characters: the unescaped form is a placeholder (`\<verb\>`, `\<adj\>`),
#: and handing a bare `<verb>` to the HTML parser is what truncated the rest of
#: the paragraph. Everything else is its own literal character.
_ESCAPE_REPLACEMENTS = {"<": "&lt;", ">": "&gt;"}

#: `\X` for any punctuation X. Applied before any markup parsing so an escaped
#: delimiter can never be read as the delimiter it is escaping.
_ESCAPED = re.compile(r"\\([^\w\s])")

#: A GFM separator row: pipes, dashes, optional alignment colons, whitespace, and
#: NOTHING else — plus at least one dash, which is what GFM itself requires. Both
#: halves matter. Without "nothing else" a data row of short dashes would qualify;
#: without "at least one dash" DoJG's `| | |` blank DATA row would be read as a
#: separator and its first row of content would vanish into a header.
#:
#: Deliberately not length-gated: GFM accepts a single dash per cell, and a source
#: that writes `|--|--|` means the same table as one that pads it to
#: `|--------|--------|`. Being stricter would silently fall back to rendering the
#: table as prose, which is the defect this module exists to fix.
_SEPARATOR_ROW = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$")

#: Any line the table reader will consider part of a pipe-line run: it both opens
#: and closes with a pipe, which every one of `yokubi`'s 220 table rows does.
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")

#: A `- ` bullet at the start of a line. `yokubi` writes no other bullet marker
#: and never indents one, so the pattern is deliberately not generalised.
_BULLET = re.compile(r"^- +(?=\S)")

#: `[text](target)`. Non-greedy on both halves so two links on one line stay
#: separate, and the target may not contain a closing paren (none of the 26 do).
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")

#: `**bold**` before `*italic*`, so the two-asterisk form is consumed first and a
#: bold run is never read as an italic run wrapping an asterisk.
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\*)")


def _link_text(match: re.Match[str]) -> str:
    """Render a Markdown link as its own visible text.

    Every link `yokubi` writes is a relative path to another lesson's Markdown
    source (`./Lesson1.md`, `../../Section1/Part1/Lesson14.md`), which is dead in a
    dictionary card — there is no document for it to be relative to — and which
    Yomitan's schema rejects outright, since `href` must match `^(?:https?:|\\?)`.

    An absolute URL would fare no better: `richtext._Converter.handle_starttag`
    drops every anchor and keeps its text ("source anchors are popout/reference
    markers pointing at the producer's own site"), and the card contract admits
    external anchors only in a `listedOnly` block. So the author's words are kept
    and the unusable target is dropped, which is exactly what the shared converter
    would do to an anchor anyway.
    """
    return match.group(1)


def _inline(text: str) -> str:
    """Convert one line's inline Markdown, leaving block structure alone."""
    text = _LINK.sub(_link_text, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def _split_row(line: str) -> list[str]:
    """Cells of one pipe row.

    Both the opening and closing pipe are fences, not cell delimiters, so they are
    removed before splitting; a `| a | b |` row is two cells, not four. Cell text
    is stripped because the author pads cells to align the table visually in the
    source, and that padding is layout, not content.
    """
    body = line.strip()
    body = body.removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in body.split("|")]


def _table(rows: list[str]) -> str:
    """Render one pipe table, given its rows including the separator.

    The header row is dropped when every one of its cells is empty: GFM *requires*
    a header row syntactically, and 33 of `yokubi`'s 44 tables supply an empty one
    because the author wanted a plain grid. Emitting it anyway put an empty
    full-width band above two thirds of the tables in the dictionary.

    Cell counts are ragged in the source (a row may carry fewer cells than the
    separator declares), so nothing is padded or truncated — each row renders the
    cells it actually has, which is what the author wrote.
    """
    separator = next(
        (index for index, line in enumerate(rows) if _SEPARATOR_ROW.match(line)), None
    )
    if separator is None:
        # Not a table after all: pipe lines with no separator are notation, not
        # layout, and are left to render as the text they are.
        return "\n".join(rows)

    header = [_split_row(line) for line in rows[:separator]]
    body = [_split_row(line) for line in rows[separator + 1 :]]
    if not any(cell for row in header for cell in row):
        header = []

    out = ["<table>"]
    if header:
        out.append("<thead>")
        for row in header:
            out.append("<tr>")
            out.extend(f"<th>{_inline(cell)}</th>" for cell in row)
            out.append("</tr>")
        out.append("</thead>")
    if body:
        out.append("<tbody>")
        for row in body:
            out.append("<tr>")
            out.extend(f"<td>{_inline(cell)}</td>" for cell in row)
            out.append("</tr>")
        out.append("</tbody>")
    out.append("</table>")
    return "".join(out)


def _table_runs(lines: list[str]) -> list[list[str]]:
    """Split a run of pipe lines into one group per table.

    A new table starts at the row BEFORE each separator after the first, because
    that row is the next table's header. `lesson-20:の` writes four tables back to
    back with no blank line, so a run is not one table by default.
    """
    separators = [i for i, line in enumerate(lines) if _SEPARATOR_ROW.match(line)]
    if len(separators) <= 1:
        return [lines]
    # Each table owns everything from its own header up to the row before the next
    # table's header. A separator at index i implies a header at i-1.
    starts = [0] + [max(index - 1, 0) for index in separators[1:]]
    groups: list[list[str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        if start < end:
            groups.append(lines[start:end])
    return groups


def _markdown_to_html(text: str) -> str:
    """Convert one Markdown prose field to the HTML subset `richtext` accepts."""
    text = _ESCAPED.sub(
        lambda m: _ESCAPE_REPLACEMENTS.get(m.group(1), m.group(1)), text
    )
    lines = text.split("\n")

    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]

        if _TABLE_ROW.match(line):
            run_end = index
            while run_end < len(lines) and _TABLE_ROW.match(lines[run_end]):
                run_end += 1
            run = lines[index:run_end]
            if any(_SEPARATOR_ROW.match(candidate) for candidate in run):
                out.extend(_table(group) for group in _table_runs(run))
                index = run_end
                continue
            # A pipe run with no separator anywhere is not a table; fall through
            # and let the lines render as prose.

        if _BULLET.match(line):
            items: list[str] = []
            while index < len(lines) and _BULLET.match(lines[index]):
                items.append(_BULLET.sub("", lines[index]).strip())
                index += 1
            out.append(
                "<ul>"
                + "".join(f"<li>{_inline(item)}</li>" for item in items)
                + "</ul>"
            )
            continue

        out.append(_inline(line))
        index += 1

    # Every newline this source writes is a hard block break (it ships no blank
    # lines at all), so they are doubled into paragraph breaks that survive
    # `richtext._join_soft_break`. Block elements already separate themselves, so
    # they are joined directly and never gain a stray empty paragraph.
    rendered: list[str] = []
    for piece in out:
        if piece.startswith(("<table>", "<ul>")):
            # A block element already separates itself. Joining it with a newline
            # would leave a whitespace text node between two back-to-back tables
            # (`lesson-20:の` writes four), which renders as a stray gap.
            rendered.append(piece)
        else:
            rendered.append(piece + "\n\n")
    return "".join(rendered)


def prose_to_html(text: str, *, source: str = "") -> str:
    """Convert a source's prose field into HTML `richtext` can render.

    A source with no declared dialect is returned unchanged, so adding this stage
    cannot alter what the other nine sources render.
    """
    if not isinstance(text, str) or not text.strip():
        return text
    if source not in MARKDOWN_SOURCES:
        return text
    return _markdown_to_html(text)


__all__ = ["MARKDOWN_SOURCES", "prose_to_html"]
