"""絵でわかる日本語 — E de wakaru.

Source: `aiko-tanaka/Grammar-Dictionaries` `edewakaru/`, revision
`edewakaru_v1.03;2022-09-01`, 1248 entries across four banks. Structured-content
entries laid out as:

    〜なりとも｜日本語能力試験　JLPT　N１文法
    【接続】 ...
    【意味】 ...
    【例文】 ①sentence  →rephrasing
    【説明】 ...

The producer's distinctive feature is that example sentences are followed by a
`→` rephrasing in plainer Japanese. Those rephrasings are the pedagogical point
of this source, so they are kept with their sentence rather than discarded or
mistaken for separate examples.

The upstream text-only variant is used deliberately. A separate community build
adds images scraped from the producer's site; those bytes would grow the package
for every entry and carry a weaker provenance claim, so this card takes the
text banks only (see the media-cost policy in the dictionary skill).
"""

from __future__ import annotations

import re

from ..model import Example, GrammarPoint
from .community import (
    CommunityBankExtractor,
    clean,
    jlpt_from_tags,
    split_sections,
)
from .registry import register_extractor
from .yomitan_bank import TermRow

_HEADINGS = {
    "接続": "structure",
    "意味": "meaning",
    "例文": "examples",
    "基本例文": "examples",
    "説明": "explanation",
    "使う時": "usage",
    "注意": "notes",
    "口語形": "colloquial",
}

#: The producer numbers examples with circled digits.
_CIRCLED = re.compile(r"^[\s　]*[①-⑳❶-❿][\s　.．、]*")
#: A plainer-Japanese restatement of the preceding sentence.
_REPHRASING = re.compile(r"^[\s　]*[→⇒][\s　]*")
_TITLE_LEVEL = re.compile(r"JLPT[\s　]*([NＮ][\s　]*[1-5１-５])")
#: Blog-ring footer and end-of-post marker the producer appends to every post.
#: Measured over the source: 2,246 `にほんブログ村` lines, 1,057 `――以上――`
#: lines and 492 `語学(日本語)ランキング` lines were shipping as dictionary
#: content, ending each explanation with repeated link captions. They are site
#: chrome, not lexicographic content. `語学(日本語)ランキング` was found by the
#: UGD-14 round-6 visual gate and occurs in exactly that one form, always as its
#: own line, so an exact-line match cannot swallow real prose.
_POST_CHROME = frozenset({
    "にほんブログ村",
    "――以上――",
    "ーー以上ーー",
    "--以上--",
    "語学(日本語)ランキング",
    "語学（日本語）ランキング",
})

#: The same markers, matched as a TRAILING RUN rather than a whole line.
#:
#: The exact-line rule above cannot see a marker the producer concatenated onto
#: the end of a sentence with no newline, and 4 such leaks reached the packaged
#: banks (`だって`, `なんで`, `みたいな`, `みたいに`). Measured over the source the
#: glued form is bounded and always a TAIL: 14 trailing `――以上――`, 2 trailing
#: `にほんブログ村`, and 13 occurrences inside a repeated tail run such as
#: `…語学(日本語)ランキングにほんブログ村にほんブログ村にほんブログ村――以上――`.
#:
#: Anchored at end-of-line and allowed to repeat, so the whole run goes in one
#: pass. Deliberately NOT a free-floating substring match: these captions could
#: legitimately be quoted mid-sentence, and only a tail is provably chrome.
_TRAILING_CHROME = re.compile(
    "(?:" + "|".join(re.escape(marker) for marker in sorted(_POST_CHROME)) + r"|[\s　])+$"
)


def _strip_post_chrome(body: str | None) -> str | None:
    """Drop the producer's blog-ring footer from a prose block.

    Handles both forms the source uses: the marker as its own line, and a run of
    markers glued onto the end of real content.
    """
    if not body:
        return body
    kept = []
    for line in body.split("\n"):
        if line.strip() in _POST_CHROME:
            continue
        # Only strip when the tail actually contains a marker, so an ordinary
        # line merely ending in whitespace is left byte-identical.
        candidate = _TRAILING_CHROME.sub("", line)
        if candidate != line and any(marker in line for marker in _POST_CHROME):
            line = candidate
        kept.append(line)
    return "\n".join(kept)


@register_extractor
class EdewakaruExtractor(CommunityBankExtractor):
    name = "edewakaru"
    label = "絵でわかる日本語"
    members = tuple(f"term_bank_{index}.json" for index in range(1, 5))

    def parse(self, row: TermRow) -> GrammarPoint | None:
        sections = split_sections(row.text, _HEADINGS)

        # The level appears in the entry's own title line (`…｜JLPT　N１文法`);
        # the term tag names the producer's difficulty band (初級/中級/上級), which
        # is not a JLPT level and must not be coerced into one.
        title_line = row.text.split("\n", 1)[0]
        level_match = _TITLE_LEVEL.search(title_line) or _TITLE_LEVEL.search(row.text)
        jlpt = jlpt_from_tags(level_match.group(1) if level_match else "")

        provenance = self.base_provenance(row)
        provenance["producerBand"] = row.term_tags
        for optional in ("usage", "notes", "colloquial"):
            if optional in sections:
                provenance[optional] = clean(_strip_post_chrome(sections[optional]))

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading),
            meaning=clean(_strip_post_chrome(sections.get("meaning"))),
            structure=clean(_strip_post_chrome(sections.get("structure"))),
            explanation=clean(_strip_post_chrome(sections.get("explanation"))),
            jlpt=jlpt,
            examples=_numbered_examples(
                _strip_post_chrome(sections.get("examples")), row.highlights
            ),
            tags=(row.term_tags,) if row.term_tags else (),
            provenance=provenance,
        )


def _numbered_examples(
    body: str | None, highlights: tuple[str, ...]
) -> tuple[Example, ...]:
    """Collect circled-digit examples, keeping each `→` rephrasing attached.

    `read_term_bank` puts every glossary node on its own line, so when the
    producer's `→` rephrasing OPENS with a bold span the arrow is left alone on
    its line (`…泣いてしまった` / `→` / `とても` / `嬉しい` / …) and the words that
    follow it are the paraphrase, not a continuation of the specimen. The earlier
    logic only started a rephrasing when text sat on the SAME line as the arrow,
    so a bare `→` was dropped and every following line glued onto the specimen —
    `嬉しさのあまり泣いてしまったとても嬉しいので泣いてしまった`, the exact run-on the
    UGD-08c beauty round filed five times (findings 1, 2, 4, 5, 13). Measured over
    edewakaru's four banks: 158 arrow-alone lines across 61 example fields; the
    3,779 arrows carrying their own text are unaffected.

    So the arrow toggles a rephrasing accumulator: once a `→` is seen, later
    continuation lines extend the CURRENT rephrasing rather than the specimen, and
    a following `→` opens the next rephrasing. A circled digit closes the example.
    """
    if not body:
        return ()
    examples: list[Example] = []
    sentence: str | None = None
    rephrasings: list[str] = []
    #: True once a `→` has opened a rephrasing for the current specimen. While set,
    #: an unmarked continuation line extends the last rephrasing, not the sentence.
    in_rephrasing = False

    def flush() -> None:
        nonlocal sentence, in_rephrasing
        if sentence:
            japanese = clean(sentence)
            if japanese:
                text = japanese
                for rephrasing in rephrasings:
                    cleaned = clean(rephrasing)
                    if cleaned:
                        text += f"\n→{cleaned}"
                marked = tuple(marker for marker in highlights if marker in japanese)
                # `english` stays None: the rephrasing is Japanese, and this
                # build never machine-translates.
                examples.append(Example(japanese=text, english=None, highlight=marked))
        sentence = None
        rephrasings.clear()
        in_rephrasing = False

    for line in body.split("\n"):
        if not line.strip():
            continue
        if _CIRCLED.match(line):
            flush()
            sentence = _CIRCLED.sub("", line).strip()
        elif _REPHRASING.match(line) and sentence:
            # A `→` opens a NEW rephrasing whether or not it carries its own text.
            # A bare arrow (the paraphrase begins with a bold span on the next
            # line) still starts one, so the words after it accumulate here rather
            # than fusing onto the specimen.
            rephrasings.append(_REPHRASING.sub("", line).strip())
            in_rephrasing = True
        elif in_rephrasing:
            rephrasings[-1] += line.strip()
        elif sentence:
            sentence += line.strip()
    flush()
    return tuple(examples)


__all__ = ["EdewakaruExtractor"]
