"""DoJG — 日本語文法辞典(全集).

Source: `aiko-tanaka/Grammar-Dictionaries` `dojg/`, revision
`DOJG_v1.01;2022-04-30`, 535 entries in one bank. Unlike the other community
sources this bank's glossary is plain text, not structured content, laid out as:

    文法項目 | くらい | 基本
     [解説]  ... English explanation
     [意味]   ... English gloss
     [例文A]  ... paired JP / EN sentences
     [例文B]  ... paired JP / EN sentences
     [接続]   ... formation table

Example blocks alternate a Japanese sentence (prefixed `(ks).` / `(a).`) and its
English translation on the following line, so translations are paired
positionally rather than machine-translated.
"""

from __future__ import annotations

import re

from ..model import Example, GrammarPoint
from .community import CommunityBankExtractor, clean, split_sections
from .registry import register_extractor
from .yomitan_bank import TermRow

#: DoJG's term tags name the print volume, not a JLPT level.
VOLUME_TAGS = {
    "DOJG基本": "基本 (Basic)",
    "DOJG中級編": "中級編 (Intermediate)",
    "DOJG上級編": "上級編 (Advanced)",
}

_HEADINGS = {
    "解説": "explanation",
    "意味": "meaning",
    "例文A": "examples_a",
    "例文B": "examples_b",
    "接続": "structure",
}

# Sentence bullets: `(ks).`, `(ksa).`, `(a).`, `(b).` …
_BULLET = re.compile(r"^[\s　]*\(([a-z]{1,4})\)[\s.．　]*")
_HEADER = re.compile(r"^[\s　]*文法項目[\s　]*\|(?P<item>[^|]*)\|(?P<volume>[^|\n]*)")


@register_extractor
class DojgExtractor(CommunityBankExtractor):
    name = "dojg"
    label = "DoJG 日本語文法辞典(全集)"
    members = ("term_bank_1.json",)

    def parse(self, row: TermRow) -> GrammarPoint | None:
        text = row.text
        sections = split_sections(text, _HEADINGS)

        header = _HEADER.search(text)
        volume_tag = row.term_tags
        volume = VOLUME_TAGS.get(volume_tag)
        if volume is None and header is not None:
            volume = clean(header.group("volume"))

        examples = _paired_examples(sections.get("examples_a")) + _paired_examples(
            sections.get("examples_b")
        )

        provenance = self.base_provenance(row)
        # The volume is DoJG's own difficulty axis. It is recorded as provenance
        # rather than mapped onto JLPT, which DoJG does not publish.
        if volume:
            provenance["volume"] = volume
        provenance["glossaryFormat"] = "plain-text"

        tags = (volume_tag,) if volume_tag else ()
        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading),
            meaning=clean(sections.get("meaning")),
            structure=clean(sections.get("structure")),
            explanation=clean(sections.get("explanation")),
            jlpt=None,
            examples=examples,
            tags=tags,
            provenance=provenance,
        )


def _paired_examples(body: str | None) -> tuple[Example, ...]:
    """Pair each bulleted Japanese sentence with the English line beneath it."""
    if not body:
        return ()
    examples: list[Example] = []
    japanese: str | None = None
    english: list[str] = []

    def flush() -> None:
        nonlocal japanese
        if japanese:
            sentence = clean(japanese)
            if sentence:
                examples.append(
                    Example(japanese=sentence, english=clean("\n".join(english)))
                )
        japanese = None
        english.clear()

    for line in body.split("\n"):
        if not line.strip():
            continue
        match = _BULLET.match(line)
        if match:
            flush()
            japanese = _BULLET.sub("", line).strip()
        elif japanese is not None:
            english.append(line.strip())
    flush()
    return tuple(examples)


__all__ = ["DojgExtractor", "VOLUME_TAGS"]
