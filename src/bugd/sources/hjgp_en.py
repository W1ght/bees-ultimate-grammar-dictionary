"""HJGP 日本語文型辞典 英語版 — bilingual Japanese-English grammar dictionary.

Source: 日本語文型辞典［英語版］ (A Handbook of Japanese Grammar Patterns for
Teachers and Learners), PyGlossary export by Selxo, 1,048 grammar entries with
English translations of every example sentence and English explanations.

Entry text layout (after flattening structured content):

    【あえて】
    1. あえて
    （1）
    Japanese sentence
    English translation
    （2）
    Japanese sentence
    English translation
    ...
    English explanation paragraph
    2. あえてV-ば
    ...

Parsing separates examples (with English translations), sense headers, and
explanations. The English explanations are the primary value of this source
over the monolingual HJGP.
"""

from __future__ import annotations

import re

from ..model import Example, GrammarPoint
from .community import CommunityBankExtractor, clean
from .registry import register_extractor
from .yomitan_bank import TermRow

_TITLE = re.compile(r"^【[^】]+】$")
_NUMBERED_EXAMPLE = re.compile(r"^（\s*\d+\s*）$")
_SENSE_NUM = re.compile(r"^\d+[.．]\s")
_XREF = re.compile(r"[⇾→]\s*【?\s*([^】\n]+?)\s*】?")
_FRONT_MATTER = frozenset({"0Index of meaning and function groups", "0Preface", "0User's Guide"})
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _is_japanese(line: str) -> bool:
    return bool(_KANA.search(line) or _HAN.search(line))


@register_extractor
class HjgpEnExtractor(CommunityBankExtractor):
    name = "hjgp_en"
    label = "日本語文型辞典 英語版"
    members = ("term_bank_1.json",)

    def parse(self, row: TermRow) -> GrammarPoint | None:
        if row.expression in _FRONT_MATTER:
            return None

        text = row.text
        stripped = text.strip()

        xref = _XREF.search(stripped)
        if xref and len(stripped) < 120:
            target = xref.group(1).strip().strip("【】")
            provenance = self.base_provenance(row)
            provenance["aliasOf"] = target
            return GrammarPoint(
                source=self.name,
                source_id=str(row.sequence) if row.sequence else row.expression,
                expression=row.expression,
                reading=clean(row.reading) or row.expression,
                provenance=provenance,
            )

        lines = text.split("\n")
        examples: list[Example] = []
        explanations: list[str] = []
        structures: list[str] = []
        pending_japanese: str | None = None

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line:
                continue

            if _TITLE.match(line):
                continue

            if _NUMBERED_EXAMPLE.match(line):
                if pending_japanese:
                    examples.append(Example(japanese=pending_japanese))
                    pending_japanese = None
                # Next line should be Japanese, then English
                if i < len(lines):
                    jp_line = lines[i].strip()
                    i += 1
                    en_line = None
                    if i < len(lines) and not _is_japanese(lines[i].strip()) and lines[i].strip() and not _NUMBERED_EXAMPLE.match(lines[i].strip()) and not _SENSE_NUM.match(lines[i].strip()):
                        en_line = lines[i].strip()
                        i += 1
                    if jp_line:
                        marked = tuple(h for h in row.highlights if h in jp_line)
                        examples.append(
                            Example(
                                japanese=jp_line,
                                english=en_line,
                                highlight=marked,
                            )
                        )
                continue

            if _SENSE_NUM.match(line):
                if pending_japanese:
                    examples.append(Example(japanese=pending_japanese))
                    pending_japanese = None
                structures.append(line)
                continue

            if pending_japanese:
                if not _is_japanese(line):
                    examples.append(
                        Example(japanese=pending_japanese, english=line)
                    )
                    pending_japanese = None
                else:
                    examples.append(Example(japanese=pending_japanese))
                    pending_japanese = line
                continue

            explanations.append(line)

        if pending_japanese:
            examples.append(Example(japanese=pending_japanese))

        meaning = clean("\n".join(explanations)) if explanations else None
        structure = clean("\n".join(structures)) if structures else None

        provenance = self.base_provenance(row)

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading) or None,
            meaning=meaning,
            structure=structure,
            examples=tuple(examples),
            tags=(row.term_tags,) if row.term_tags else (),
            provenance=provenance,
        )


__all__ = ["HjgpEnExtractor"]
