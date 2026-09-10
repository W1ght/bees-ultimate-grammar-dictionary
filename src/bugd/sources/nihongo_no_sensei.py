"""Nihongo no Sensei — 毎日のんびり日本語教師.

Source: `aiko-tanaka/Grammar-Dictionaries` `nihongo_no_sensei/`, revision
`nihongo_no_sensei_v_1.04;2022-07-03`, 1479 entries across five banks (one per
level band). Structured-content entries laid out as:

    【Ｎ１文法】～以外の何ものでもない
    接続   ...
    意味   不是别的，正是…      <- Chinese
           まさしく～だ。        <- Japanese
    解説   ...                   <- Japanese
    例文   （１） sentence
                （Chinese translation）
    備考   ...

Two source-specific facts drive this extractor:

**The producer writes for Chinese-speaking learners.** Its `意味` block and its
per-example parenthesised translations are Chinese, while `解説` is Japanese.
Passing Chinese text through as an English or Japanese gloss would be a false
language claim, so Chinese lines are separated into `provenance["meaningZh"]`
and `Example.english` is left `None` — this build never presents a translation
in a language it did not verify, and never machine-translates.

**The bank contains deliberate synthetic deinflection entries.** Upstream
documents creating "fake" headwords (e.g. `以外の何ものでもある` beside
`以外の何ものでもない`) purely so Yomitan's deinflector catches more conjugations.
They repeat another entry's body verbatim. They are kept — they are the reason
lookup works — but flagged `syntheticLookupForm: True` so the merge stage can
fold them instead of rendering the same content twice.
"""

from __future__ import annotations

import dataclasses
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
    "解説": "explanation",
    "例文": "examples",
    "備考": "notes",
    "注意": "notes",
}

#: Producer example numbering: （１）… （10）.
_NUMBERED = re.compile(r"^[\s　]*[（(][\s　]*\d{1,3}[\s　]*[)）][\s　]*")
#: A wholly parenthesised line following a sentence: the Chinese translation.
_PARENTHESISED = re.compile(r"^[\s　]*[（(](?P<body>.*)[)）][\s　]*$")
#: Producer end-of-entry sentinel, not content.
_SENTINEL = re.compile(r"-{2,}\s*END\s*-{2,}", re.IGNORECASE)
#: The producer credits contributors on their own line, e.g. `（四ツ谷カオル 様）`.
_CONTRIBUTOR = re.compile(r"^[\s　]*[（(].{1,30}様[)）][\s　]*$")

# Characters that appear in Simplified Chinese but not in modern Japanese
# orthography. Presence of any is strong evidence a line is Chinese, which is
# more reliable here than kana-absence alone: a short Japanese phrase in all
# kanji would otherwise be misclassified.
_SIMPLIFIED_MARKERS = frozenset(
    "个们这那么没试华东车马门问题风银课说识请谁话语读书写华产严丽举义乐买卖强"
    "对开关间闻长张进远运还边过来经给结绍继续网罗义习练习员单纪级红约给"
)
_KANA = re.compile(r"[\u3040-\u30ff]")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{3}")

#: Chinese punctuation and the Chinese gloss placeholder.
#:
#: `，` is the Chinese enumeration comma; Japanese writes `、`.
#:
#: `…` is the decisive one. This producer writes its Chinese glosses with `…`
#: standing for the slot (`取决于…`, `与…相同`, `连…都…`) while its Japanese glosses
#: use the corpus's own `〜` placeholder (`〜によっては`, `〜次第で（は）`). The
#: character-marker set below cannot cover the vocabulary: it missed 870 lines
#: (`非常…`, `按照…`, `只有…`, `极其…`), and extending it word by word is unbounded.
#:
#: Measured over the WHOLE corpus, lines that are kana-free, Latin-free, contain
#: Han, and contain `…` number 2,513 -- and every one is Chinese. The only
#: kana-free `…` lines that are not Chinese are `母：…` (a speaker label carrying
#: no Han at all), which the Han requirement already excludes.
_CHINESE_MARKS = re.compile(r"[\uff0c\u2026]")


#: A speaker label opening the line (`母：`, `A:`). Such a line is dialogue, not a
#: gloss, and `母：…` would otherwise satisfy the Han + `…` test below.
_SPEAKER_PREFIX = re.compile(r"^[^：:\s]{1,4}[：:]")
#: A circled sense enumerator opening a line. This producer uses the same glyphs
#: for BOTH columns, so the enumerator alone carries no language information --
#: it only matters together with the entry's own evidence (see
#: `_split_by_language`).
_ENUMERATED = re.compile(r"^[\u2460-\u2473\u2776-\u277f]")


def is_chinese_line(line: str) -> bool:
    """True when a line is Chinese rather than Japanese.

    Kana is decisive evidence of Japanese, and so is a Latin word (an English
    gloss). Otherwise the line is Chinese when it carries Han plus a Chinese
    punctuation/placeholder mark, or a Simplified-only character.

    Lines that remain ambiguous -- all-shared-Han with no Chinese mark, such as
    `以前` or `五段動詞` -- are treated as Japanese, because under-claiming a
    translation is safer than labelling Japanese text as Chinese.
    """
    if _KANA.search(line) or _LATIN_WORD.search(line):
        return False
    if not _HAN.search(line):
        return False
    # A dialogue turn is not a gloss: `母：…` is a speaker trailing off.
    if _SPEAKER_PREFIX.match(line):
        return False
    if _CHINESE_MARKS.search(line):
        return True
    return any(character in _SIMPLIFIED_MARKERS for character in line)


@register_extractor
class NihongoNoSenseiExtractor(CommunityBankExtractor):
    name = "nihongo_no_sensei"
    label = "毎日のんびり日本語教師"
    members = tuple(f"term_bank_{index}.json" for index in range(1, 6))

    def parse(self, row: TermRow) -> GrammarPoint | None:
        text = _SENTINEL.sub("", row.text)
        sections = split_sections(text, _HEADINGS)

        # The level is stated in the entry's own 【Ｎ１文法】 title. Term tags such
        # as `日本語教師―Ｎ０` mark points outside the JLPT scale, so a missing
        # level stays missing.
        title_line = text.split("\n", 1)[0]
        jlpt = jlpt_from_tags(title_line, row.term_tags)

        japanese_meaning, chinese_meaning = _split_by_language(sections.get("meaning"))

        provenance = self.base_provenance(row)
        provenance["producerBand"] = row.term_tags
        if chinese_meaning:
            # Recorded with an explicit language, never rendered as the entry's
            # gloss: the card contract segregates non-verified languages.
            provenance["meaningZh"] = chinese_meaning
        if "notes" in sections:
            provenance["notes"] = clean(sections["notes"])

        examples, contributors = _numbered_examples(
            sections.get("examples"), row.highlights
        )
        if contributors:
            provenance["producerContributors"] = contributors

        return GrammarPoint(
            source=self.name,
            source_id=str(row.sequence) if row.sequence else row.expression,
            expression=row.expression,
            variants=row.variants,
            reading=clean(row.reading),
            meaning=japanese_meaning,
            structure=clean(sections.get("structure")),
            explanation=clean(sections.get("explanation")),
            notes=clean(sections.get("notes")),
            jlpt=jlpt,
            examples=examples,
            tags=(row.term_tags,) if row.term_tags else (),
            provenance=provenance,
        )

    def finalize(self, points: list[GrammarPoint]) -> list[GrammarPoint]:
        """Flag the synthetic deinflection headwords upstream created.

        These share another entry's body verbatim and exist only to widen
        Yomitan's deinflection reach. The first row carrying a given body is the
        real entry (banks are level-ordered and upstream appends the fake form
        directly after the real one); later rows repeating it are synthetic.
        """
        first_seen: dict[tuple[str | None, str | None, str | None], str] = {}
        flagged: list[GrammarPoint] = []
        for point in points:
            body = (point.meaning, point.structure, point.explanation)
            if not any(body):
                flagged.append(point)
                continue
            canonical = first_seen.get(body)
            if canonical is None:
                first_seen[body] = point.expression
                flagged.append(point)
                continue
            provenance = dict(point.provenance)
            provenance["syntheticLookupForm"] = True
            provenance["canonicalExpression"] = canonical
            flagged.append(dataclasses.replace(point, provenance=provenance))
        return flagged


def _split_by_language(body: str | None) -> tuple[str | None, str | None]:
    """Split a mixed 意味 block into its Japanese and Chinese lines.

    Two passes, because a Chinese gloss is only sometimes self-identifying. The
    first pass classifies each line on its own evidence (`is_chinese_line`). The
    second uses POSITION: this producer writes its Chinese column first and its
    Japanese gloss after it, so an ambiguous kana-free line inside that leading
    bilingual run belongs to the same Chinese column.

    That second pass is what catches the four-character idioms
    (`首屈一指`, `永无止境`, `难以形容`, `完全不一样`) which carry neither the `…`
    placeholder nor a Simplified-only character, and which no character-level rule
    can separate from Japanese: of the 224 distinct Han in that residue, only 18
    never occur in this corpus's Japanese text. It cannot mislabel a record the
    producer wrote no Chinese for, because it requires an already-confirmed Chinese
    line in the same field.

    The run is scanned as a WHOLE rather than only forward from the first
    confirmed Chinese line. Ordering the other way round is common -- the producer
    puts its shortest gloss first -- so a forward-only pass left `一样` (`ながらに`),
    `首屈一指` (`きっての`) and 25 other records shipping Chinese as the entry's
    compact meaning and sense heading; the UGD-14 round-8 visual gate filed
    `…左右 大概… …多 与…相同 和…一样` as an unreadable heading.

    One carve-out: an enumerated line (`①根拠`) is kept when the entry's own
    enumeration proves itself Japanese by carrying kana somewhere in it, as
    `によって` does with `④受身（受身文の動作主）`. Without that proof an enumerated
    line is treated like any other, because `②表示后悔,遗憾` and `②一直／全身心地`
    are enumerated Chinese. Measured over the source: 26 records change, 23 lose
    their (Chinese) Japanese-column text entirely, and zero records gain a line.
    """
    if not body:
        return None, None
    lines = [line.strip() for line in body.split("\n") if line.strip()]

    def japanese_evidence(line: str) -> bool:
        """Kana or a Latin word is decisive evidence of Japanese/English."""
        return bool(_KANA.search(line) or _LATIN_WORD.search(line))

    # The leading bilingual run ends at the first decisively-Japanese line.
    run_end = next(
        (index for index, line in enumerate(lines) if japanese_evidence(line)),
        len(lines),
    )
    run_has_chinese = any(is_chinese_line(line) for line in lines[:run_end])
    enumeration_is_japanese = any(
        _ENUMERATED.match(line) and japanese_evidence(line) for line in lines
    )

    japanese: list[str] = []
    chinese: list[str] = []
    for index, line in enumerate(lines):
        if is_chinese_line(line):
            chinese.append(line)
            continue
        # An ambiguous kana-free line inside the leading Chinese run.
        if (
            index < run_end
            and run_has_chinese
            and _HAN.search(line)
            and not (enumeration_is_japanese and _ENUMERATED.match(line))
        ):
            chinese.append(line)
            continue
        japanese.append(line)
    return clean("\n".join(japanese)), clean("\n".join(chinese))


def _numbered_examples(
    body: str | None, highlights: tuple[str, ...]
) -> tuple[tuple[Example, ...], list[str]]:
    """Collect numbered examples, dropping their Chinese translation lines."""
    if not body:
        return (), []
    examples: list[Example] = []
    contributors: list[str] = []
    sentence: str | None = None

    def flush() -> None:
        nonlocal sentence
        if sentence:
            japanese = clean(sentence)
            if japanese:
                marked = tuple(marker for marker in highlights if marker in japanese)
                # `english` is None by policy: the producer's translation is
                # Chinese, so claiming an English translation would be false.
                examples.append(
                    Example(japanese=japanese, english=None, highlight=marked)
                )
        sentence = None

    for line in body.split("\n"):
        if not line.strip():
            continue
        if _CONTRIBUTOR.match(line):
            credit = clean(line.strip().strip("（()）"))
            if credit and credit not in contributors:
                contributors.append(credit)
            continue
        if _NUMBERED.match(line):
            flush()
            sentence = _NUMBERED.sub("", line).strip()
            continue
        parenthesised = _PARENTHESISED.match(line)
        if parenthesised and sentence:
            # A fully parenthesised follow-on line is the Chinese translation.
            if not is_chinese_line(parenthesised.group("body")):
                sentence += line.strip()
            continue
        if sentence:
            sentence += line.strip()
    flush()
    return tuple(examples), contributors


__all__ = ["NihongoNoSenseiExtractor", "is_chinese_line"]
