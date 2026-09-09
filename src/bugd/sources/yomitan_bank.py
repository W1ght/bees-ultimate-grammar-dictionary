"""Shared reader for community Yomitan term banks.

Four of the six UGD-06 sources (`dojg`, `donna_toki`, `nihongo_net`,
`edewakaru`, `nihongo_no_sensei`) arrive as already-published Yomitan format-3
term banks rather than as raw site HTML. That is the whole reason those sources
were includable without scraping, so the shared work is *reading* a term bank,
not fetching one.

A format-3 term-bank row is a fixed 8-tuple:

    [expression, reading, definitionTags, deinflectors, score, glossary,
     sequence, termTags]

`glossary` entries are either plain strings or Yomitan structured content. This
module flattens both into text plus the substrings the producer marked bold,
because the producer's bold spans are the only trustworthy record of which
substring is the grammar point inside an example sentence. Reconstructing that
by string search would mislabel sentences where the point appears twice or in a
conjugated form.

Nothing here interprets a *specific* source's section layout: per-source parsing
lives in that source's module, so a layout change in one site cannot silently
corrupt another.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..jsonio import MalformedPayload, load_json

# A format-3 term-bank row has exactly these eight positions.
TERM_ROW_LENGTH = 8

_EXPRESSION = 0
_READING = 1
_DEFINITION_TAGS = 2
_DEINFLECTORS = 3
_GLOSSARY = 5
_SEQUENCE = 6
_TERM_TAGS = 7


@dataclass
class TermRow:
    """One normalized row of a community Yomitan term bank."""

    expression: str
    reading: str
    definition_tags: str
    deinflectors: str
    sequence: int
    term_tags: str
    #: Flattened glossary text, one string per glossary item.
    text: str
    #: Substrings the producer marked bold, in document order, deduplicated.
    highlights: tuple[str, ...] = ()
    #: Outbound links the producer embedded (kept as provenance, never as gloss).
    links: tuple[str, ...] = ()
    #: Bank member the row came from, for per-file provenance.
    member: str = ""

    @property
    def variants(self) -> tuple[str, ...]:
        """Additional lookup forms the producer recorded.

        These sources put alternate written forms in `definitionTags` (for
        example `〜ないでもない・〜なくもない`). They are lookup aliases, not tags,
        so they belong in `GrammarPoint.variants`.
        """
        raw = self.definition_tags.strip()
        if not raw:
            return ()
        forms: list[str] = []
        for candidate in raw.replace("／", "・").replace("/", "・").split("・"):
            form = candidate.strip().lstrip("〜～").strip()
            if form and form != self.expression and form not in forms:
                forms.append(form)
        return tuple(forms)


@dataclass
class _Flattened:
    parts: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


def read_term_bank(raw: bytes, *, member: str) -> list[TermRow]:
    """Parse one term-bank member, failing closed on a malformed row."""
    payload = load_json(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise MalformedPayload(f"{member}: a term bank must be a JSON array")

    rows: list[TermRow] = []
    for index, row in enumerate(payload):
        if not isinstance(row, list) or len(row) != TERM_ROW_LENGTH:
            raise MalformedPayload(
                f"{member}[{index}]: expected a {TERM_ROW_LENGTH}-element term row"
            )
        expression = row[_EXPRESSION]
        if not isinstance(expression, str) or not expression.strip():
            raise MalformedPayload(f"{member}[{index}]: empty expression")

        glossary = row[_GLOSSARY]
        if not isinstance(glossary, list):
            raise MalformedPayload(f"{member}[{index}]: glossary must be an array")
        flattened = _Flattened()
        for item in glossary:
            _flatten(item, flattened)

        sequence = row[_SEQUENCE]
        rows.append(
            TermRow(
                expression=expression,
                reading=_text_field(row[_READING]),
                definition_tags=_text_field(row[_DEFINITION_TAGS]),
                deinflectors=_text_field(row[_DEINFLECTORS]),
                sequence=sequence if isinstance(sequence, int) else 0,
                term_tags=_text_field(row[_TERM_TAGS]),
                text="\n".join(part for part in flattened.parts if part),
                highlights=_unique(flattened.highlights),
                links=_unique(flattened.links),
                member=member,
            )
        )
    return rows


def _text_field(value: object) -> str:
    return value if isinstance(value, str) else ""


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        stripped = value.strip()
        if stripped:
            seen.setdefault(stripped, None)
    return tuple(seen)


def _flatten(node: object, out: _Flattened, *, bold: bool = False) -> None:
    """Flatten a glossary item into text, bold spans, and links."""
    if isinstance(node, str):
        out.parts.append(node)
        if bold:
            out.highlights.append(node)
        return
    if isinstance(node, list):
        for child in node:
            _flatten(child, out, bold=bold)
        return
    if not isinstance(node, dict):
        return

    if node.get("type") == "structured-content":
        _flatten(node.get("content"), out, bold=bold)
        return

    tag = node.get("tag")
    if tag == "a":
        href = node.get("href")
        if isinstance(href, str):
            out.links.append(href)
        # The anchor's own label is producer chrome ("edewakaru link"), not
        # dictionary content, so it is deliberately not appended as text.
        return
    if tag == "br":
        out.parts.append("\n")
        return

    style = node.get("style")
    is_bold = bold or (isinstance(style, dict) and style.get("fontWeight") == "bold")
    _flatten(node.get("content"), out, bold=is_bold)


__all__ = ["TermRow", "read_term_bank", "TERM_ROW_LENGTH"]
