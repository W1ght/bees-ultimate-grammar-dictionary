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
"""

from __future__ import annotations

import html
import re

from ..anki import AnkiNote, read_apkg_notes
from ..furigana_fixups import normalize_furigana, normalize_jlpt_field
from ..jsonio import MalformedPayload
from ..model import Example, GrammarPoint
from ..normalize import lookup_keys, sentence_key, split_alternatives
from ..richtext import strike_omissions
from .base import Extractor, ExtractResult, load_source_lock, write_points_jsonl
from .registry import register_extractor

#: The locked `.apkg` member, and the notetype whose notes are grammar points.
APKG_NAME = "Bunpro Grammar Reference.apkg"
NOTETYPE = "Bunpro Grammar Model Final V3"

#: Bunpro's level labels that map onto the JLPT scale. `Non-JLPT` and `関西弁`
#: (Kansai dialect) deliberately mark a point as *off* the scale and yield None
#: rather than an invented level. `bugd.furigana_fixups.normalize_jlpt_field`
#: owns that mapping so one shared parser serves both Anki decks; the table is
#: kept here only as the documented enumeration of what the field contains.
BUNPRO_LEVELS = ("JLPT5", "JLPT4", "JLPT3", "JLPT2", "JLPT1", "Non-JLPT", "関西弁")

_RT = re.compile(r"<rt\b[^>]*>.*?</rt>", re.DOTALL)
_RP = re.compile(r"<rp\b[^>]*>.*?</rp>", re.DOTALL)
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
    surface text, the `<rt>` reading is annotation. `<rp>` goes with it — those
    are the fallback parentheses a browser shows *only* when it cannot render
    ruby, so keeping them would put an empty `（）` into the surface string for
    the sentences that ship them. Returns None for an empty result so a blank
    field never becomes an empty string on the record.

    Omission markup is rewritten to struck plain text FIRST. `Structure` uses
    `<del>` on the ending a conjugation drops before attaching the next one
    (`食べ<del>る</del> + ます` = "drop る, add ます"), and this flattener strips
    every tag equally, so without the rewrite the marking vanished and the field
    asserted `食べる + ます` — a form that is not Japanese. Measured over the locked
    deck: 431 `<del>` runs across 80 Structure fields, and no other field.

    Player markup (`<audio>`/`<button onclick>`/`<svg>`) is dropped with its
    subtree first — see `_PLAYER` for why that is an explicit policy rather than
    a side effect of stripping tags.
    """
    if raw is None:
        return None
    text = _drop_players(raw)
    text = strike_omissions(text) or ""
    text = _RT.sub("", text)
    text = _RP.sub("", text)
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


#: Bunpro's per-example audio player: an `<audio>` element, a `<button>` whose
#: `onclick` calls `.play()` on it by id, and an inline `<svg>` play icon. Every
#: one of these is dropped WITH ITS SUBTREE and explicitly, not left to a
#: tag-stripping regex, because they are not content and they carry three
#: separate hazards into anything downstream that handles raw source HTML:
#:
#: * `onclick` is an inline JS event handler. Yomitan's structured-content
#:   renderer has no attribute channel that could emit one, so nothing is
#:   exploitable today — but passing script text through the pipeline at all is an
#:   unnecessary surface, and the drop should be a stated policy rather than a
#:   side effect of `_TAG.sub`.
#: * `src="audio_NNN_M_female.opus"` names a media file this dictionary does not
#:   repackage. Shipped, it renders as a broken silent control.
#: * `id="audio_NNN_rest_M"` is unique per note, not per corpus, so ids from
#:   different notes collide once several notes' HTML is concatenated.
#:
#: Measured over the locked deck: 14,881 players in `Rest_Examples_HTML`, plus
#: 3,945 in `Explanation` and 2,680 in `Explanation_JP`, which embed the same
#: `.example-item` markup inside `div.embedded-examples` — 21,506 in total. A
#: guard scoped to `Rest_Examples_HTML` alone would miss 6,625 of them, so this
#: runs over every field the extractor reads.
_PLAYER = re.compile(
    r"<(audio|button|svg)\b[^>]*>.*?</\1\s*>|<(?:audio|source|track|path)\b[^>]*/?>",
    re.DOTALL | re.IGNORECASE,
)

#: Interactive/media markup that must never reach a normalized record. Asserted
#: by the regression suite over the whole corpus and over the packaged ZIP.
INTERACTIVE_MARKUP = re.compile(
    r"<(?:audio|button|svg|path|video|source|track|script|iframe)\b|\bon[a-z]+\s*=",
    re.IGNORECASE,
)


def _drop_players(raw: str) -> str:
    """Remove audio/button/svg player nodes and their subtrees.

    Applied before any text extraction, so the player's `onclick` body, `.opus`
    reference and per-note element id are gone before the field is parsed rather
    than merely absent from the result by luck.
    """
    previous = None
    current = raw
    # Nested/adjacent players: rewrite until stable.
    while current != previous:
        previous = current
        current = _PLAYER.sub("", current)
    return current


def _examples(field: str) -> tuple[Example, ...]:
    """Build examples from a `Rest_Examples_HTML` field, deduped by surface text.

    A note occasionally repeats a sentence; it is attached once. An item without
    a Japanese sentence is skipped rather than emitted as an empty example.

    Only the Japanese sentence and the English translation are read out of each
    `.example-item`; the item's audio player is never part of either. The
    annotated `japanese_html` kept on the record is additionally run through
    `_drop_players`, because that field is stored as RAW source HTML and travels
    to the bank stage — the only field that does — so it is the one place a player
    node could otherwise ride along.
    """
    examples: list[Example] = []
    seen: set[str] = set()
    for block in _example_blocks(field):
        ja_match = _JAPANESE_DIV.search(block)
        if ja_match is None:
            continue
        japanese_html = _drop_players(ja_match.group(1)).strip()
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

    def extract(self) -> ExtractResult:
        self._fixups_applied = 0
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

        # The reviewable per-source artifact: one normalized record per line,
        # beside the locked bytes it came from.
        jsonl_path = write_points_jsonl(self.input_dir, points)

        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "notes": len(notes),
                "points": len(points),
                "notetype": NOTETYPE,
                "withExamples": sum(1 for point in points if point.examples),
                "withJlpt": sum(1 for point in points if point.jlpt),
                "examples": sum(len(point.examples) for point in points),
                "jsonl": jsonl_path.name,
                # Dedup-relevant identity, reported so a reviewer can see what
                # the merge stage will group on without re-deriving it.
                "distinctSourceIds": len({point.source_id for point in points}),
                "distinctLookupKeys": len(
                    {key for point in points for key in lookup_keys(point.expression)}
                ),
                "pointsWithVariants": sum(1 for point in points if point.variants),
                "distinctSentenceKeys": len(
                    {
                        sentence_key(example.japanese)
                        for point in points
                        for example in point.examples
                    }
                ),
                "furiganaFixupsApplied": self._fixups_applied,
            },
        )

    def _parse(self, note: AnkiNote) -> GrammarPoint:
        fields = note.fields
        expression = _flatten(self._fix(fields.get("Title")))
        if not expression:
            raise MalformedPayload(
                f"{self.name}: note {note.note_id} has no Title headword"
            )

        source_id = (fields.get("ID") or "").strip() or str(note.note_id)
        jlpt_label = (fields.get("JLPT") or "").strip()
        # One shared parser for both Anki decks: it folds `JLPT5` onto `N5` and
        # deliberately leaves `Non-JLPT` / `関西弁` off the scale as a note.
        jlpt, jlpt_note = normalize_jlpt_field(jlpt_label)

        provenance: dict[str, object] = {
            "sourceLabel": self.label,
            "notetype": NOTETYPE,
            "grammarOrder": (fields.get("Grammar_Order") or "").strip() or None,
        }
        # Bunpro's own level label is recorded verbatim even when it does not map
        # onto JLPT, so `Non-JLPT` / `関西弁` points stay distinguishable.
        if jlpt_label:
            provenance["bunproLevel"] = jlpt_label
        if note.tags:
            provenance["ankiTags"] = list(note.tags)

        # Alternates the source itself advertises in one headword (`けど・だけど`)
        # become additional lookup forms, so both spellings resolve to this
        # record instead of only the first.
        variants = tuple(
            form for form in split_alternatives(expression) if form != expression
        )

        return GrammarPoint(
            source=self.name,
            source_id=source_id,
            expression=expression,
            variants=variants,
            reading=None,
            meaning=_flatten(self._fix(fields.get("Meaning"))),
            structure=_flatten(self._fix(fields.get("Structure"))),
            nuance=_flatten(self._fix(fields.get("Nuance"))),
            nuance_ja=_flatten(self._fix(fields.get("Nuance_JP"))),
            explanation=_flatten(self._fix(fields.get("Explanation"))),
            explanation_ja=_flatten(self._fix(fields.get("Explanation_JP"))),
            notes=jlpt_note,
            jlpt=jlpt,
            examples=_examples(self._fix(fields.get("Rest_Examples_HTML")) or ""),
            tags=tuple(note.tags),
            provenance=provenance,
        )

    def _fix(self, raw: str | None) -> str | None:
        """Apply the audited UGD-11a furigana fix-ups to one raw field.

        Counts the fields it actually changed so the extract stats can state how
        many corrections landed rather than asserting the table is wired up.
        """
        if raw is None:
            return None
        fixed = normalize_furigana(raw)
        if fixed != raw:
            self._fixups_applied += 1
        return fixed


__all__ = [
    "BunproExtractor",
    "APKG_NAME",
    "NOTETYPE",
    "BUNPRO_LEVELS",
    "INTERACTIVE_MARKUP",
]
