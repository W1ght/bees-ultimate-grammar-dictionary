"""Yokubi — The Common Grammar Guide (https://yoku.bi).

No Yomitan dictionary or structured export of Yokubi exists, so this extractor
reads the upstream mdBook markdown acquired by `scripts/acquire_yokubi.py`
(`Morgawr/yokubi`, CC BY 4.0). The rendered site is never scraped.

Yokubi's declared structure decides what this extractor may claim. Its 64 lesson
files carry exactly one `# ` H1 each and no subheadings anywhere, so the smallest
unit Yokubi itself declares is *the lesson*, not a grammar point. Segmenting a
lesson into grammar points would mean inventing boundaries the source does not
draw, which the card forbids. Three rules follow:

* a headword may only come from a Japanese token the lesson title declares;
* a lesson whose title declares no Japanese headword is reported as skipped with
  that reason recorded, never segmented by guesswork;
* an example attaches to a headword only when the example text contains it;
  otherwise it stays counted as lesson-scoped context.

`SUMMARY.md` is the lesson index, and each lesson's own H1 is the authoritative
title (SUMMARY labels drift: `い adjectives` vs `い-adjectives`). Every lesson
`SUMMARY.md` lists must be present in the source lock, so a partial corpus fails
closed rather than silently yielding fewer entries.

Redistribution: CC BY 4.0 permits redistribution with attribution, so records
are `licenseTier: "A"`, `redistributable: True`, and every point carries the
required attribution string.
"""

from __future__ import annotations

import html
import pathlib
import re

from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult
from .registry import register_extractor

#: Human-facing attribution rendered on every merged entry sourced from Yokubi.
ATTRIBUTION = "Yokubi — The Common Grammar Guide (https://yoku.bi), CC BY 4.0"
#: CC BY 4.0 permits redistribution with attribution.
LICENSE_TIER = "A"
REDISTRIBUTABLE = True

#: Where the acquired mdBook lives inside `data/sources/yokubi/`.
SUMMARY_PATH = "src/SUMMARY.md"

# A SUMMARY.md lesson bullet, e.g. `  - [Lesson 1: State of being ...](./x.md)`.
_LINK = re.compile(r"^\s*- \[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
_LESSON_LABEL = re.compile(r"^Lesson\s+(?P<number>\d+):\s*(?P<title>.+)$")

# One character in a Japanese script: hiragana, katakana, prolonged-sound mark,
# iteration mark, and the CJK unified/compat/extension-A kanji ranges.
_JAPANESE = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u30fc\u3005\u4e00-\u9fff\uf900-\ufaff\u3400-\u4dbf]"
)
# Title separators that never belong inside a headword.
_SPLIT = re.compile(r"[\s,、。/／:：()（）\"'\u201c\u201d]+")

_FURIGANA = re.compile(r"\{f\|([^|{}]+)\|([^|{}]+)\}")
_TAG = re.compile(r"<[^>]*>")


def strip_markup(text: str) -> str:
    """Reduce mdBook/HTML markup to the plain surface text.

    Furigana annotations `{f|漢字|かんじ}` collapse to their base form, inline
    HTML tags are dropped, and HTML entities are unescaped so that a substring
    test against Japanese text behaves the way a reader would expect.
    """
    text = _FURIGANA.sub(lambda m: m.group(1), text)
    text = _TAG.sub("", text)
    return html.unescape(text)


def is_japanese(token: str) -> bool:
    """True when `token` contains at least one Japanese-script character."""
    return bool(_JAPANESE.search(token))


def title_headwords(title: str) -> list[str]:
    """The ordered, de-duplicated Japanese headwords a lesson title declares.

    A headword may only originate from a Japanese token the title itself names;
    English words in the title never become headwords. Returns `[]` when the
    title declares no Japanese token at all (a skipped, title-less lesson).
    """
    out: list[str] = []
    for token in _SPLIT.split(title):
        token = token.strip().strip("〜~-–—.")
        if not token or not is_japanese(token):
            continue
        for piece in token.split("〜"):
            piece = piece.strip()
            if piece and is_japanese(piece) and piece not in out:
                out.append(piece)
    return out


def lesson_h1(body: str) -> str:
    """The lesson's own authoritative H1 title (first `# ` line), or ``""``."""
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def lesson_examples(body: str) -> list[Example]:
    """Every Japanese example line the lesson declares.

    Yokubi lays examples out in `<pre>` blocks as a Japanese line optionally
    followed by an English gloss. We keep each Japanese line that carries a
    Japanese-script character; a following non-Japanese line becomes its gloss.
    No boundary the source doesn't draw is invented — this only reads the lines
    already present.
    """
    examples: list[Example] = []
    for block in re.findall(r"<pre>(.*?)</pre>", body, flags=re.DOTALL | re.IGNORECASE):
        lines = [strip_markup(raw).strip() for raw in block.split("\n")]
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if not line:
                idx += 1
                continue
            if is_japanese(line):
                english: str | None = None
                nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
                if nxt and not is_japanese(nxt):
                    english = nxt
                    idx += 1
                examples.append(Example(japanese=line, english=english))
            idx += 1
    return examples


@register_extractor
class YokubiExtractor(Extractor):
    """Extract one grammar point per title-declared headword from Yokubi."""

    name = "yokubi"
    label = ATTRIBUTION
    ai_generated_source = False

    def _iter_summary_lessons(self, summary_text: str):
        """Yield `(number, href, lock_key)` for each lesson SUMMARY.md lists."""
        for line in summary_text.split("\n"):
            link = _LINK.match(line)
            if not link:
                continue
            label = _LESSON_LABEL.match(link.group("label").strip())
            if not label:
                continue
            href = link.group("href").strip()
            rel = href.lstrip("./")
            lock_key = f"src/{rel}" if not rel.startswith("src/") else rel
            yield int(label.group("number")), href, lock_key

    def extract(self) -> ExtractResult:
        lock = self.read_locked_bytes  # bound; validates digest + membership
        summary_bytes = self.read_locked_bytes(SUMMARY_PATH)
        summary_text = summary_bytes.decode("utf-8")

        points: list[GrammarPoint] = []
        consumed: dict[str, str] = {SUMMARY_PATH: "index"}
        skipped: list[dict[str, object]] = []
        lesson_count = 0
        example_total = 0
        attached_total = 0

        for number, href, lock_key in self._iter_summary_lessons(summary_text):
            lesson_count += 1
            # Fails closed: read_locked_bytes raises SourceLockError if a lesson
            # SUMMARY.md lists is absent from the lock or the bytes drifted.
            body = lock(lock_key).decode("utf-8")
            consumed[lock_key] = "lesson"

            title = lesson_h1(body)
            heads = title_headwords(title)
            examples = lesson_examples(body)
            example_total += len(examples)

            if not heads:
                skipped.append(
                    {
                        "lesson": number,
                        "href": href,
                        "title": title,
                        "reason": "title declares no Japanese headword",
                    }
                )
                continue

            for head in heads:
                attached = tuple(ex for ex in examples if head in ex.japanese)
                attached_total += len(attached)
                points.append(
                    GrammarPoint(
                        source=self.name,
                        source_id=f"lesson-{number}:{head}",
                        expression=head,
                        examples=attached,
                        provenance={
                            "lesson": number,
                            "lessonTitle": title,
                            "href": href,
                            "attribution": ATTRIBUTION,
                            "licenseTier": LICENSE_TIER,
                            "redistributable": REDISTRIBUTABLE,
                            "lessonExampleCount": len(examples),
                        },
                    )
                )

        stats: dict[str, object] = {
            "lessons": lesson_count,
            "headwordPoints": len(points),
            "skippedLessons": skipped,
            "skippedCount": len(skipped),
            "exampleLines": example_total,
            "attachedExamples": attached_total,
            "attribution": ATTRIBUTION,
            "licenseTier": LICENSE_TIER,
            "redistributable": REDISTRIBUTABLE,
        }
        return ExtractResult(
            source=self.name, points=points, consumed=consumed, stats=stats
        )


__all__ = [
    "YokubiExtractor",
    "ATTRIBUTION",
    "LICENSE_TIER",
    "REDISTRIBUTABLE",
    "title_headwords",
    "lesson_h1",
    "lesson_examples",
    "strip_markup",
    "is_japanese",
]
