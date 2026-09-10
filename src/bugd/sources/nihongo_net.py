"""日本語NET — JLPT文法解説まとめ.

Source: `aiko-tanaka/Grammar-Dictionaries` `nihongo_kyoushi/`, revision
`nihongo_kyoshi_v1.03;2022-05-27`, 628 entries across six banks (one per JLPT
level plus an explicitly non-JLPT bank). Structured-content entries laid out as:

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
}

_TITLE = re.compile(r"文法・例文[：:]\s*(?P<title>[^\n】]+)")
_EXAMPLE_MARKERS = "・･•"


@register_extractor
class NihongoNetExtractor(CommunityBankExtractor):
    name = "nihongo_net"
    label = "日本語NET JLPT文法解説まとめ"
    members = tuple(f"term_bank_{index}.json" for index in range(1, 7))

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

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading),
            meaning=clean(sections.get("meaning")),
            structure=clean(sections.get("structure")),
            explanation=clean(sections.get("explanation")),
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
