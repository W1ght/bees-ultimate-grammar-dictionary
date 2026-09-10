"""Shared extractor base for community Yomitan-bank grammar sources.

The five community sources differ only in how one entry's flattened text splits
into meaning / structure / explanation / examples. Acquisition, lock
verification, member discovery, JLPT derivation and the JSONL side-artifact are
identical, so they live here and each source module supplies only its parser.

Two policies are enforced for every community source:

* **JLPT levels are read, never guessed.** `jlpt_from_tags` returns a level only
  when the producer's own term tag names one. DoJG's tags name print volumes
  (基本/中級編/上級編), not JLPT levels, and Donna Toki has no level tag at all, so
  both correctly yield `None` rather than an invented level.
"""

from __future__ import annotations

import pathlib
import re

from ..jsonio import MalformedPayload, dump_json
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, assign_row_uids, load_source_lock
from .polarity_repair import repair_point
from .yomitan_bank import TermRow, read_term_bank

#: Per-source JSONL lands beside the locked bytes so a reviewer can read one
#: source's normalized records without running the merge stage.
JSONL_NAME = "points.jsonl"

_JLPT_PATTERN = re.compile(r"[NＮ]\s*([1-5１-５])")
_FULLWIDTH_DIGITS = str.maketrans("１２３４５", "12345")


def jlpt_from_tags(*tags: str) -> str | None:
    """Return the JLPT level a producer tag names, or None.

    Only an explicit `N1`–`N5` (in either width) counts. Producer tags such as
    `日本語教師―Ｎ０` and `日本語NETーJLPTに出ない？文型` deliberately mark points as
    *outside* the JLPT scale; they must not be coerced onto it.
    """
    for tag in tags:
        if not tag:
            continue
        match = _JLPT_PATTERN.search(tag)
        if match:
            return "N" + match.group(1).translate(_FULLWIDTH_DIGITS)
    return None


def split_sections(text: str, headings: dict[str, str]) -> dict[str, str]:
    """Split flattened entry text into named sections.

    `headings` maps a producer heading (as it appears in the text, without
    decoration) to a canonical section name. A heading matches when it is the
    only content on its line, optionally wrapped in the producer's brackets
    (`【】` or `[]`) — matching mid-sentence occurrences would truncate bodies
    that merely mention the word 意味 or 接続.
    """
    canonical = {heading: name for heading, name in headings.items()}
    pattern = "|".join(re.escape(heading) for heading in canonical)
    if not pattern:
        return {}
    line_pattern = re.compile(
        rf"^[\s　]*(?:【[\s　]*)?(?:\[[\s　]*)?({pattern})(?:[\s　]*\])?(?:[\s　]*】)?[\s　]*$",
        re.MULTILINE,
    )

    matches = list(line_pattern.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = canonical[match.group(1)]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body and name not in sections:
            sections[name] = body
    return sections


#: A line that CONTINUES the previous one rather than starting a new paragraph.
#:
#: These producers put a highlighted grammar point on its own line, so a sentence
#: arrives split across three lines:
#:
#:     １時間悩んだ
#:     あげく
#:     、買わなかった
#:
#: `bugd.richtext` preserves those as paragraph breaks, and the card then either
#: renders three blocks or joins them with a space -- which is what the UGD-14
#: round-8 visual gate reported as `１時間悩んだ あげく 、買わなかった`, "unnatural extra
#: spaces ... even before Japanese punctuation".
#:
#: A line starting with closing punctuation or a closing bracket cannot begin a
#: paragraph, so that break is a layout artifact and the line is rejoined to the
#: one above. Measured over the corpus: 1,122 occurrences, 1,022 of them in
#: edewakaru explanations.
_CONTINUATION_LINE = re.compile(r"^[、。！？，)）」』】]")


#: A space before Japanese sentence punctuation.
#:
#: Japanese has no inter-word space, so `準備をしただけに 、いい点が` is a producer
#: artifact, not typography: it renders as a visible gap where a comma should sit
#: flush against the preceding character. Measured over the corpus, 16 occurrences
#: across 3 sources, and all 16 are defects.
#:
#: `、。！？` only. NOT `，`, which this corpus uses in Latin enumerations
#: (`as in ❹ ～ ❻ 、`) where a preceding space can be intentional.
_SPACE_BEFORE_JA_PUNCT = re.compile(r"[ \u3000]+(?=[、。！？])")


def _rejoin_continuations(text: str) -> str:
    """Fold a line opening with closing punctuation back onto the previous line."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if out and stripped and _CONTINUATION_LINE.match(stripped):
            out[-1] = out[-1].rstrip() + stripped
        else:
            out.append(line)
    return "\n".join(out)


def clean(value: str | None) -> str | None:
    """Collapse producer whitespace, returning None for an empty result."""
    if value is None:
        return None
    # Producer text mixes ideographic spaces, tabs and runs of blank lines.
    collapsed = re.sub(r"[ \t\u3000]+", " ", value.replace("\r\n", "\n"))
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    collapsed = "\n".join(line.strip() for line in collapsed.split("\n"))
    collapsed = _rejoin_continuations(collapsed)
    collapsed = _SPACE_BEFORE_JA_PUNCT.sub("", collapsed).strip()
    return collapsed or None


class CommunityBankExtractor(Extractor):
    """Base class for a source published as Yomitan term banks."""

    #: Bank members to read, in order. Set by each source module.
    members: tuple[str, ...] = ()

    def parse(self, row: TermRow) -> GrammarPoint | None:
        """Turn one term row into a GrammarPoint, or None to skip it."""
        raise NotImplementedError

    def finalize(self, points: list[GrammarPoint]) -> list[GrammarPoint]:
        """Post-process the whole source, for facts only visible across rows.

        Default is identity. A source overrides this when a per-row parser
        cannot see what it needs — for example detecting synthetic deinflection
        headwords, which are only recognisable by comparing bodies between rows.
        """
        return points

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)
        missing = [name for name in self.members if name not in lock]
        if missing:
            raise MalformedPayload(
                f"{self.name}: locked bank members are missing: {', '.join(missing)}"
            )

        rows: list[TermRow] = []
        consumed: dict[str, str] = {}
        for member in self.members:
            raw = self.read_locked_bytes(member)
            consumed[member] = lock[member]["sha256"]
            rows.extend(read_term_bank(raw, member=member))

        points: list[GrammarPoint] = []
        skipped = 0
        for row in rows:
            point = self.parse(row)
            if point is None:
                skipped += 1
                continue
            points.append(point)

        points = self.finalize(points)
        # Repair headwords the publisher flipped to the affirmative in the
        # `expression` column while its own `reading` still spells the fixed
        # negative. Fail-closed and driven by the source's own reading; see
        # bugd.sources.polarity_repair. Applied after finalize so a source's
        # cross-row post-processing sees the publisher's original surfaces first.
        repaired_points: list[GrammarPoint] = []
        repaired = 0
        for point in points:
            fixed = repair_point(point)
            if fixed is not point and fixed.expression != point.expression:
                repaired += 1
            repaired_points.append(fixed)
        points = repaired_points

        # Row identity is stamped before the sidecar is written so the reviewable
        # JSONL and the artifact agree on it; `ExtractResult` re-checks it.
        points = assign_row_uids(self.name, points)
        self.write_jsonl(points)
        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "bankRows": len(rows),
                "points": len(points),
                "skipped": skipped,
                "polarityRepaired": repaired,
                "members": list(self.members),
                "withExamples": sum(1 for point in points if point.examples),
                "withJlpt": sum(1 for point in points if point.jlpt),
            },
        )

    def base_provenance(self, row: TermRow) -> dict[str, object]:
        provenance: dict[str, object] = {
            "sourceLabel": self.label,
            "bankMember": row.member,
            "producerTermTags": row.term_tags,
        }
        if row.links:
            provenance["producerLinks"] = list(row.links)
        if row.deinflectors:
            provenance["partOfSpeech"] = row.deinflectors
        return provenance

    def write_jsonl(self, points: list[GrammarPoint]) -> pathlib.Path:
        """Write this source's records as JSONL beside its locked bytes."""
        from ..pipeline import point_to_json

        path = self.input_dir / JSONL_NAME
        path.write_text(
            "".join(dump_json(point_to_json(point)) + "\n" for point in points),
            encoding="utf-8",
        )
        return path


def examples_from_lines(
    body: str | None,
    *,
    markers: str,
    highlights: tuple[str, ...],
    english_follows: bool = False,
) -> tuple[Example, ...]:
    """Collect example sentences from a producer example block.

    `markers` is a character class of the bullet glyphs a producer uses. Only the
    substrings the producer marked bold are attached as `highlight`: a sentence's
    grammar point is not re-derived by searching for the headword, which would
    mislabel conjugated or repeated occurrences.
    """
    if not body:
        return ()
    bullet = re.compile(rf"^[\s　]*[{markers}]+[\s　.．、,]*")
    examples: list[Example] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        japanese = clean(pending[0])
        if not japanese:
            pending.clear()
            return
        english = clean("\n".join(pending[1:])) if english_follows else None
        marked = tuple(text for text in highlights if text in japanese)
        examples.append(Example(japanese=japanese, english=english, highlight=marked))
        pending.clear()

    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            if not english_follows:
                flush()
            continue
        if bullet.match(line):
            flush()
            pending.append(bullet.sub("", line).strip())
        elif pending and english_follows:
            pending.append(stripped)
        elif not examples and not pending:
            # Text before the first bullet is section prose, not an example.
            continue
    flush()
    return tuple(examples)


__all__ = [
    "CommunityBankExtractor",
    "JSONL_NAME",
    "clean",
    "examples_from_lines",
    "jlpt_from_tags",
    "split_sections",
]
