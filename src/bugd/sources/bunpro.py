"""Bunpro — Bunpro Grammar Reference.

Source: a local Anki `.apkg` export of Bunpro's grammar reference, notetype
`Bunpro Grammar Model Final V3`, 964 notes / 964 grammar points. Unlike the
community Yomitan-bank sources this is an Anki package: a ZIP whose collection
member is a (zstd-compressed) SQLite database. `bugd.anki.read_apkg_notes`
handles the archive, the decompression, the runtime `unicase` collation and the
field-name lookup; this module only maps one note's named fields onto a
`GrammarPoint`.

Each note carries eleven fields:

    Grammar_Order | ID | Title | Meaning | JLPT | Structure |
    Nuance | Nuance_JP | Explanation | Explanation_JP | Rest_Examples_HTML

`Title` is the headword. `Meaning` is the English gloss. `JLPT` is Bunpro's own
level label (`JLPT5`..`JLPT1`, plus `Non-JLPT` and `関西弁` for points off the
scale). `Nuance`/`Nuance_JP` and `Explanation`/`Explanation_JP` are parallel
English/Japanese prose. Every substantive field is HTML: `<strong>` emphasis,
`<ruby>`/`<rt>` furigana, and Bunpro's own `<span class="gp-popout">` /
`<span class="info-highlight">` cross-reference chrome. Prose fields are
flattened to plain text here — turning source markup into rendered content is
the bank stage's job, not an extractor's.

Examples live in `Rest_Examples_HTML` as a run of `<div class="example-item">`
blocks, each pairing a `<div class="japanese">` sentence with a
`<div class="english">` translation. The Japanese carries `<ruby>` furigana and
marks the grammar point with `<span class="highlight">`; that annotated form is
preserved verbatim as `Example.japanese_html` while `Example.japanese` holds the
flattened surface text (base characters only, readings dropped) so the two agree
about what the sentence says. `highlight` is taken from the source's own
`highlight` spans, never re-derived by searching for the headword. The same
sentences are also embedded inside `Explanation`; those are deliberately ignored
so an example is attached once, from the field that exists to hold examples.

Redistribution: Bunpro is a paid subscription service and this content is its
proprietary material. Regardless of the user's clearance to *use* the export
locally, it is not clearly redistributable, so records are marked
`licenseTier: "C"`, `redistributable: False` — mirroring `dojg.py`. The separate
licensing gate (UGD-15) decides mechanically what may ever be published.
"""

from __future__ import annotations

import html
import re

from ..anki import AnkiNote, read_apkg_notes
from ..jsonio import MalformedPayload
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock
from .registry import register_extractor

#: The locked `.apkg` member, and the notetype whose notes are grammar points.
APKG_NAME = "Bunpro Grammar Reference.apkg"
NOTETYPE = "Bunpro Grammar Model Final V3"

#: Bunpro's level labels that map onto the JLPT scale. `Non-JLPT` and `関西弁`
#: (Kansai dialect) deliberately mark a point as *off* the scale and yield None
#: rather than an invented level.
_JLPT_MAP = {
    "JLPT5": "N5",
    "JLPT4": "N4",
    "JLPT3": "N3",
    "JLPT2": "N2",
    "JLPT1": "N1",
}

_RT = re.compile(r"<rt\b[^>]*>.*?</rt>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\u3000]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# One example block, and the paired sentence/translation divs inside it. Bunpro
# emits both single- and double-quoted class attributes, hence the character
# class on the quote.
_EXAMPLE_ITEM = re.compile(r"<div class=[\"']example-item[\"']", re.DOTALL)
_JAPANESE_DIV = re.compile(r"<div class=[\"']japanese[\"']\s*>(.*?)</div>", re.DOTALL)
_ENGLISH_DIV = re.compile(r"<div class=[\"']english[\"']\s*>(.*?)</div>", re.DOTALL)
_HIGHLIGHT_SPAN = re.compile(
    r"<span class=[\"']highlight[\"']\s*>(.*?)</span>", re.DOTALL
)


def _flatten(raw: str | None) -> str | None:
    """Flatten source HTML to plain text, dropping furigana readings.

    `<ruby>私<rt>わたし</rt></ruby>` flattens to `私`: the base characters are the
    surface text, the `<rt>` reading is annotation. Returns None for an empty
    result so a blank field never becomes an empty string on the record.
    """
    if raw is None:
        return None
    text = _RT.sub("", raw)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text or None


def _example_blocks(field: str) -> list[str]:
    """Split an example field into its per-item HTML blocks."""
    if not field:
        return []
    parts = _EXAMPLE_ITEM.split(field)
    # The first split fragment is whatever preceded the first item (section
    # chrome), never an example itself.
    return parts[1:]


def _examples(field: str) -> tuple[Example, ...]:
    """Build examples from a `Rest_Examples_HTML` field, deduped by surface text.

    A note occasionally repeats a sentence; it is attached once. An item without
    a Japanese sentence is skipped rather than emitted as an empty example.
    """
    examples: list[Example] = []
    seen: set[str] = set()
    for block in _example_blocks(field):
        ja_match = _JAPANESE_DIV.search(block)
        if ja_match is None:
            continue
        japanese_html = ja_match.group(1).strip()
        japanese = _flatten(japanese_html)
        if not japanese or japanese in seen:
            continue
        seen.add(japanese)

        en_match = _ENGLISH_DIV.search(block)
        english = _flatten(en_match.group(1)) if en_match is not None else None

        highlights = tuple(
            highlight
            for highlight in (
                _flatten(marked) for marked in _HIGHLIGHT_SPAN.findall(japanese_html)
            )
            if highlight
        )

        examples.append(
            Example(
                japanese=japanese,
                english=english,
                highlight=highlights,
                # Only keep the annotated form when it genuinely carries markup
                # beyond the flattened surface text.
                japanese_html=japanese_html if japanese_html != japanese else None,
            )
        )
    return tuple(examples)


@register_extractor
class BunproExtractor(Extractor):
    name = "bunpro"
    label = "Bunpro Grammar Reference"
    #: License tier and redistribution posture recorded on every record.
    license_tier = "C"
    redistributable = False

    def extract(self) -> ExtractResult:
        # Fail closed: the apkg must be the exact locked bytes. `load_source_lock`
        # rejects a missing/malformed lock; `read_locked_bytes` rejects a missing
        # file or a digest / byte-count mismatch.
        lock = load_source_lock(self.input_dir)
        if APKG_NAME not in lock:
            raise MalformedPayload(
                f"{self.name}: locked input is missing: {APKG_NAME}"
            )
        raw = self.read_locked_bytes(APKG_NAME)
        consumed = {APKG_NAME: lock[APKG_NAME]["sha256"]}

        notes = read_apkg_notes(raw, notetype=NOTETYPE)
        points = [self._parse(note) for note in notes]

        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "notes": len(notes),
                "points": len(points),
                "notetype": NOTETYPE,
                "licenseTier": self.license_tier,
                "redistributable": self.redistributable,
                "withExamples": sum(1 for point in points if point.examples),
                "withJlpt": sum(1 for point in points if point.jlpt),
                "examples": sum(len(point.examples) for point in points),
            },
        )

    def _parse(self, note: AnkiNote) -> GrammarPoint:
        fields = note.fields
        expression = _flatten(fields.get("Title"))
        if not expression:
            raise MalformedPayload(
                f"{self.name}: note {note.note_id} has no Title headword"
            )

        source_id = (fields.get("ID") or "").strip() or str(note.note_id)
        jlpt_label = (fields.get("JLPT") or "").strip()
        jlpt = _JLPT_MAP.get(jlpt_label)

        provenance: dict[str, object] = {
            "sourceLabel": self.label,
            "licenseTier": self.license_tier,
            "redistributable": self.redistributable,
            "notetype": NOTETYPE,
            "grammarOrder": (fields.get("Grammar_Order") or "").strip() or None,
        }
        # Bunpro's own level label is recorded verbatim even when it does not map
        # onto JLPT, so `Non-JLPT` / `関西弁` points stay distinguishable.
        if jlpt_label:
            provenance["bunproLevel"] = jlpt_label
        if note.tags:
            provenance["ankiTags"] = list(note.tags)

        return GrammarPoint(
            source=self.name,
            source_id=source_id,
            expression=expression,
            reading=None,
            meaning=_flatten(fields.get("Meaning")),
            structure=_flatten(fields.get("Structure")),
            nuance=_flatten(fields.get("Nuance")),
            nuance_ja=_flatten(fields.get("Nuance_JP")),
            explanation=_flatten(fields.get("Explanation")),
            explanation_ja=_flatten(fields.get("Explanation_JP")),
            jlpt=jlpt,
            examples=_examples(fields.get("Rest_Examples_HTML") or ""),
            tags=tuple(note.tags),
            provenance=provenance,
        )


__all__ = ["BunproExtractor", "APKG_NAME", "NOTETYPE"]
