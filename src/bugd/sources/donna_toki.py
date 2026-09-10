"""Donna Toki — どんなときどう使う 日本語表現文型辞典.

Source: `donna_v1.04;2022-04-30`, format 3, 1082 entries in one bank, acquired
from a public mirror because the banks were removed from aiko-tanaka's
repository before its current HEAD. The acquisition step corroborates the mirror
against the independently distributed `…文型辞典_1_05.zip` and fails closed if
they disagree, so the mirror is not trusted on its own.

Entries come in two shapes, and conflating them would be the main way to get
this source wrong:

**Substantive entries** (660) carry reading, a short English gloss, numbered
example sentences, a 接続 block, a Japanese explanation, an optional 参照
cross-reference, and an English explanation:

    あいだ
    throughout (the time…)
     ❶ わたしは夏の間、ずっと北海道にいました。
    接続
    〔普通形〕（ナＡな／Ｎの）＋間
    ｢間｣は時間幅のある状態を…
    参照︰あいだに
    Appends to expressions of time, i.e., "throughout the entire time."

**Alias redirects** (422) are lookup-only stubs whose body is a reading and a
`➡` pointing at the entry that holds the content. They are emitted with
`aliasOf` provenance and no fabricated body: dropping them would break lookup
for the alternate written form, and inventing content for them would be worse.
"""

from __future__ import annotations

import re

from ..model import Example, GrammarPoint
from .community import CommunityBankExtractor, clean, split_sections
from .registry import register_extractor
from .yomitan_bank import TermRow

_HEADINGS = {"接続": "structure"}

#: Producer example numbering uses filled circled digits.
_FILLED_CIRCLED = re.compile(r"^[\s　]*[❶-❿①-⑳][\s　.．、]*")
#: Redirect arrow used by alias stubs.
_ARROW = "➡"
#: Cross-reference line, e.g. `参照︰あいだに`.
_CROSS_REFERENCE = re.compile(r"参照[︰:：][\s　]*(?P<target>.+)")
#: Producer search/navigation chrome appended to every entry; not content.
_CHROME = re.compile(
    r"(google\.com/search\?q=.*|itazuraneko\.neocities\.org/\S*)", re.IGNORECASE
)
#: A line of Latin prose is the producer's English explanation.
_LATIN = re.compile(r"[A-Za-z]")
_KANA_OR_HAN = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
#: Sentence terminators that can precede the producer's appended index key.
#: Both the ASCII and the fullwidth period occur; the fullwidth one accounts for
#: 285 of the 302 measured cases on its own.
_INDEX_KEY_TERMINATORS = '.．。"”』」！？!?)）'


@register_extractor
class DonnaTokiExtractor(CommunityBankExtractor):
    name = "donna_toki"
    label = "どんなときどう使う 日本語表現文型辞典"
    members = ("term_bank_1.json",)

    def parse(self, row: TermRow) -> GrammarPoint | None:
        text = _CHROME.sub("", row.text)
        sections = split_sections(text, _HEADINGS)
        provenance = self.base_provenance(row)

        # Everything before the 接続 heading (or the whole body when absent) is
        # the head block: reading, gloss, examples, prose.
        head = text.split("\n接続", 1)[0] if "\n接続" in text else text
        tail = sections.get("structure", "")

        cross_reference = _CROSS_REFERENCE.search(text)
        if cross_reference:
            target = clean(cross_reference.group("target"))
            if target:
                provenance["seeAlso"] = target

        if _is_alias_stub(text):
            # A lookup-only alias. Its target is the entry the arrow points at,
            # which for this producer is the reading printed above the arrow.
            provenance["aliasOf"] = clean(row.reading) or row.expression
            provenance["entryShape"] = "alias-redirect"
            return GrammarPoint(
                source=self.name,
                source_id=str(row.sequence) if row.sequence else row.expression,
                expression=row.expression,
                variants=row.variants,
                reading=clean(row.reading),
                jlpt=None,
                tags=(row.term_tags,) if row.term_tags else (),
                provenance=provenance,
            )

        provenance["entryShape"] = "substantive"
        reading = clean(row.reading)
        gloss, examples, japanese_prose = _parse_head(head, row)
        structure, tail_japanese, english_prose = _parse_tail(tail, reading)
        # Belt and braces: also strip a key the head block glued onto its prose.
        japanese_prose = _strip_trailing_index_key(japanese_prose, reading)
        english_prose = _strip_trailing_index_key(english_prose, reading)

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=reading,
            # The short English line is this source's gloss; the Japanese and
            # English prose blocks are its explanation. Both are producer-written
            # translations, so neither is machine-generated here.
            meaning=gloss,
            structure=structure,
            explanation=clean(
                "\n\n".join(
                    part
                    for part in (japanese_prose, tail_japanese, english_prose)
                    if part
                )
            ),
            jlpt=None,
            examples=examples,
            tags=(row.term_tags,) if row.term_tags else (),
            provenance=provenance,
        )


def _is_alias_stub(text: str) -> bool:
    """True when an entry is a lookup-only redirect rather than content."""
    if _ARROW not in text:
        return False
    body = text.replace(_ARROW, "")
    # A redirect's remaining body is just the reading; a substantive entry that
    # happens to contain an arrow still has sentences and headings.
    return len(clean(body) or "") < 40


def _parse_head(head: str, row: TermRow) -> tuple[str | None, tuple[Example, ...], str | None]:
    """Split the head block into gloss, examples, and Japanese prose."""
    gloss: str | None = None
    examples: list[Example] = []
    prose: list[str] = []
    reading = (row.reading or "").strip()

    for line in head.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == reading or stripped == row.expression:
            continue
        if _FILLED_CIRCLED.match(line):
            sentence = clean(_FILLED_CIRCLED.sub("", line))
            if sentence:
                marked = tuple(marker for marker in row.highlights if marker in sentence)
                examples.append(
                    Example(japanese=sentence, english=None, highlight=marked)
                )
            continue
        if gloss is None and _LATIN.search(stripped) and not _KANA_OR_HAN.search(stripped):
            # The first Latin-only line is the producer's short English gloss.
            gloss = clean(stripped)
            continue
        if _CROSS_REFERENCE.search(stripped):
            continue
        prose.append(stripped)

    return gloss, tuple(examples), clean("\n".join(prose))


def _parse_tail(tail: str, reading: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Split the 接続 block into formation pattern, JA prose, and EN prose.

    The producer packs three different things after the 接続 heading: the
    formation pattern on the first line, a Japanese explanation, and an English
    explanation. Keeping only the first line (an easy mistake) would silently
    drop this source's entire explanatory content, so all three are returned.

    The index key is stripped per line BEFORE language classification: the key is
    kana, so an English sentence carrying it (`...conditions follow.あいだ`) looks
    like mixed script and was being filed as Japanese prose.
    """
    pattern: str | None = None
    japanese: list[str] = []
    english: list[str] = []

    for line in tail.split("\n"):
        stripped = _strip_trailing_index_key(line.strip(), reading) or ""
        if not stripped or _CROSS_REFERENCE.search(stripped):
            continue
        if _LATIN.search(stripped) and not _KANA_OR_HAN.search(stripped):
            english.append(stripped)
            continue
        if pattern is None:
            pattern = stripped
            continue
        japanese.append(stripped)

    return clean(pattern), clean("\n".join(japanese)), clean("\n".join(english))


def _strip_trailing_index_key(text: str | None, reading: str | None) -> str | None:
    """Drop the producer's index key from the end of a prose block.

    This producer's English prose ends with the entry's own reading appended
    directly to the last sentence, with no separator -- the bank stores
    `...conditions follow.あいだ` for 間/あいだ. It is the index key its site uses
    for the anchor link, not prose, and in the rendered card it looked like a
    text-run bug. Measured over the corpus: 302 fields end with their reading
    immediately after a sentence terminator.

    Only that exact shape is stripped. 48 other fields also end with their
    reading, but as a deliberate variant list on its own line (`\\n〜ばいい／...`),
    so requiring a terminator and NO preceding newline keeps real content.
    """
    if not text or not reading:
        return text
    if not text.endswith(reading) or len(text) <= len(reading):
        return text
    before = text[: -len(reading)]
    if not before.strip():
        return text
    # A trailing newline means the reading is its own line: a variant list.
    if before != before.rstrip("\n"):
        return text
    if before.rstrip()[-1:] not in _INDEX_KEY_TERMINATORS:
        return text
    return before.rstrip() or None


__all__ = ["DonnaTokiExtractor"]
