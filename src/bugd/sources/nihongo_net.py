"""日本語NET — JLPT文法解説まとめ.

Source: scraped from nihongokyoshi-net.com JLPT grammar pages. Banks are split
one per JLPT level. Structured-content entries laid out as:

    【   【JLPT N１】文法・例文：〜あっての   】
    [意味]     ...
    [接続]     ...
    [JLPT レベル]  N1
    例文
    ・sentence
    ・sentence

The producer states the JLPT level twice (term tag and a `[JLPT レベル]` line), so
it is read rather than inferred. Its `日本語NETーJLPTに出ない？文型` bank marks points
that are deliberately *outside* the JLPT scale; those keep `jlpt: None`.
"""

from __future__ import annotations

import re

from ..model import GrammarPoint
from .base import load_source_lock
from .community import (
    CommunityBankExtractor,
    clean,
    examples_from_lines,
    jlpt_from_tags,
    split_sections,
)
from .registry import register_extractor
from .yomitan_bank import TermRow

_HEADINGS = {
    "意味": "meaning",
    "接続": "structure",
    "JLPT レベル": "level",
    "JLPTレベル": "level",
    "例文": "examples",
    "教案": "lesson_plan",
    "解説": "explanation",
    "英訳": "english",
}

_TITLE = re.compile(r"文法・例文[：:]\s*(?P<title>[^\n】]+)")
_EXAMPLE_MARKERS = "・･•"


@register_extractor
class NihongoNetExtractor(CommunityBankExtractor):
    name = "nihongo_net"
    label = "日本語NET JLPT文法解説まとめ"
    @property
    def members(self) -> tuple[str, ...]:
        lock = load_source_lock(self.input_dir)
        banks = sorted(k for k in lock if k.startswith("term_bank_") and k.endswith(".json"))
        return tuple(banks)

    def parse(self, row: TermRow) -> GrammarPoint | None:
        sections = split_sections(row.text, _HEADINGS)

        # Prefer the producer's own `[JLPT レベル]` line, then its term tag. The
        # non-JLPT bank names no level in either place, so it stays None.
        jlpt = jlpt_from_tags(sections.get("level", ""), row.term_tags)

        provenance = self.base_provenance(row)
        title = _TITLE.search(row.text)
        if title:
            provenance["producerTitle"] = clean(title.group("title"))
        if "lesson_plan" in sections:
            provenance["lessonPlan"] = clean(sections["lesson_plan"])

        english = clean(sections.get("english"))
        explanation = clean(sections.get("explanation"))
        if english and explanation:
            explanation = f"{english}\n\n{explanation}"
        elif english:
            explanation = english

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading),
            meaning=clean(sections.get("meaning")),
            structure=clean(sections.get("structure")),
            explanation=explanation,
            jlpt=jlpt,
            examples=examples_from_lines(
                sections.get("examples"),
                markers=_EXAMPLE_MARKERS,
                highlights=row.highlights,
            ),
            tags=(row.term_tags,) if row.term_tags else (),
            provenance=provenance,
        )


__all__ = ["NihongoNetExtractor"]
