"""Yokubi — The Common Grammar Guide (https://yoku.bi).

No Yomitan dictionary or structured export of Yokubi exists, so this extractor
reads the upstream mdBook markdown acquired by `scripts/acquire_yokubi.py`
(`Morgawr/yokubi`). The rendered site is never scraped.

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
"""

from __future__ import annotations

import html
import pathlib
import re

from ..jsonio import MalformedPayload, dump_json, load_json
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, SourceLockError, load_source_lock
from .registry import register_extractor

#: Per-source JSONL lands beside the locked bytes, matching the community
#: sources' convention so a reviewer can read one source's normalized records
#: without running the merge stage.
JSONL_NAME = "points.jsonl"

#: Human-readable coverage report naming every lesson covered or skipped, with
#: the reason recorded for each skip.
COVERAGE_NAME = "COVERAGE.md"

#: How this source is credited on every card it contributes to.
YOKUBI_ATTRIBUTION = "Yokubi — The Common Grammar Guide (https://yoku.bi)"
SITE = "https://yoku.bi/"

#: Reason recorded for a lesson Yokubi teaches without declaring a Japanese
#: headword in its own title. These lessons are real content, but Yokubi draws
#: no lookupable surface for them, so they are reported rather than segmented.
LESSON_ONLY_REASON = (
    "lesson title declares no Japanese headword; Yokubi's smallest declared unit "
    "is the lesson and it publishes no sub-headings, so no lookup form exists "
    "without inventing a grammar-point boundary"
)

#: Reason recorded for an example group whose lines are not a source-paired
#: Japanese sentence (conjugation tables, pronoun lists, English-only asides).
UNPAIRED_REASON = (
    "example group is not a source-paired Japanese sentence (conjugation or "
    "vocabulary table, or English-only aside); no translation is invented"
)

# ---------------------------------------------------------------------------
# script classification
# ---------------------------------------------------------------------------

#: Kana, kana iteration/prolongation marks, and CJK ideographs including the
#: repetition mark 々. Pinned to the blocks Yokubi actually uses; a token needs
#: one of these to be a Japanese headword candidate.
_JAPANESE = re.compile(
    r"[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fc\u30fd\u30fe"
    r"\u3005\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")

#: mdBook furigana preprocessor markers (`book.toml` `[preprocessor.furigana]`),
#: written `{f|kanji|reading}`. Degraded to the surface kanji: the reading is
#: ruby decoration, and a malformed marker must not leak braces into a headword.
_FURIGANA = re.compile(r"\{f\|([^|{}]*)\|[^|{}]*\}")

_BOLD = re.compile(r"<b>(.*?)</b>", re.S)
_TAGS = re.compile(r"</?(?:b|i|u|em|strong|ins|del|s|br)\s*/?>", re.I)
_PRE_BLOCK = re.compile(r"<pre>(.*?)</pre>", re.S)
_H1 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)

#: `SUMMARY.md` list entry: `  - [Lesson 3: ...](./Section1/Part1/Lesson3.md)`.
_SUMMARY_ENTRY = re.compile(r"^[ \t]*-[ \t]*\[([^\]]+)\]\((\.?/?[^)]+\.md)\)[ \t]*$", re.M)
_LESSON_NUMBER = re.compile(r"Lesson(\d+)\.md$")

#: A title's Japanese tokens are separated by ASCII/Japanese punctuation and by
#: English connective words. Tildes mark a placeholder slot (`〜たり〜たり`) and a
#: slash marks alternatives (`ても/でも`), so both are separators, not headword
#: characters.
_TITLE_SPLIT = re.compile(r"[,、，/／・\s\u3000\u301c\uff5e~]+")

#: Trailing/leading decoration a title puts around a form it declares.
_TRIM = '"\u201c\u201d\'\u2018\u2019()（）[]「」『』:：;；.。!！?？*'

#: Latin-script words a title uses to talk *about* the forms it declares. A
#: token containing Japanese never matches these, so they only guard the
#: separator pass.
_STOP_WORDS = frozenset({"and", "or", "with", "plus", "the", "form", "etc"})


def strip_inline_markup(text: str) -> str:
    """Reduce Yokubi inline markup to clean surface text.

    Yokubi marks emphasis with `<b>`, escapes its slot placeholders as HTML
    entities (`&lt;verb&gt;`), and marks ruby with mdBook's `{f|kanji|reading}`.
    All three degrade to the text a reader sees; nothing is invented and no
    marker residue survives into a headword or a sentence.
    """
    without_tags = _TAGS.sub("", text)
    without_furigana = _FURIGANA.sub(r"\1", without_tags)
    return html.unescape(without_furigana)


def title_headwords(title: str) -> tuple[str, ...]:
    """Return the Japanese forms a lesson title itself declares, in order.

    This is the only headword source. A title such as `Adversatives with が, けど,
    しかし, and ても/でも` declares five forms; `The causative form` declares none
    and yields `()` so the caller reports it as skipped instead of guessing.
    """
    cleaned = strip_inline_markup(title)
    seen: dict[str, None] = {}
    for raw in _TITLE_SPLIT.split(cleaned):
        token = raw.strip().strip(_TRIM).strip()
        if not token or token.lower() in _STOP_WORDS:
            continue
        if not _JAPANESE.search(token):
            continue
        # A token like `こそあど words` cannot survive the separator pass, but a
        # hyphenated `い-adjectives` can: keep only its Japanese run.
        for part in re.split(r"[-\u2010-\u2015]+", token):
            candidate = part.strip().strip(_TRIM).strip()
            if candidate and _JAPANESE.search(candidate) and not _LATIN_WORD.search(candidate):
                seen.setdefault(candidate, None)
    return tuple(seen)


def _bold_spans(raw_line: str) -> tuple[str, ...]:
    """The clean surface text of every ``<b>`` span Yokubi marks in a line."""
    spans: list[str] = []
    for inner in _BOLD.findall(raw_line):
        text = strip_inline_markup(inner).strip()
        if text:
            spans.append(text)
    return tuple(spans)


def _classify(line: str) -> str:
    """Classify a cleaned example line as Japanese (``J``), English (``E``), or
    mixed (``M``).

    A line that carries a Japanese-script character *and* a Latin word is mixed
    (a conjugation gloss such as ``見る／見ます, ichidan verb.``): Yokubi did not
    write it as a source-paired sentence, so it is reported rather than split
    into an invented Japanese/English pair.
    """
    has_jp = bool(_JAPANESE.search(line))
    has_latin = bool(_LATIN_WORD.search(line))
    if has_jp and has_latin:
        return "M"
    if has_jp:
        return "J"
    return "E"


def parse_examples(body: str) -> tuple[list[Example], list[dict[str, object]]]:
    """Read the example sentences a lesson declares in its ``<pre>`` blocks.

    Yokubi lays examples out in ``<pre>`` blocks as blank-line-separated groups.
    A group is either a Japanese sentence on its own or a Japanese sentence
    followed by its English gloss; ``<b>`` spans become highlight spans and
    ``{f|kanji|reading}`` furigana degrade to surface text. Returns
    ``(examples, skipped)`` where ``skipped`` records every group whose lines do
    not form a source-paired sentence (conjugation tables, pronoun lists,
    English-only asides) with the group's line-shape and a reason, so nothing is
    invented and no unpaired group silently vanishes.
    """
    examples: list[Example] = []
    skipped: list[dict[str, object]] = []

    for block in _PRE_BLOCK.findall(body):
        # Split the block into blank-line-separated groups, preserving raw lines
        # (with markup) so we can recover the source's own highlight spans.
        groups: list[list[str]] = []
        current: list[str] = []
        for raw in block.split("\n"):
            if raw.strip():
                current.append(raw)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        for group in groups:
            cleaned = [strip_inline_markup(raw).strip() for raw in group]
            shape = "".join(_classify(line) for line in cleaned)

            if shape == "J":
                examples.append(
                    Example(
                        japanese=cleaned[0],
                        english=None,
                        highlight=_bold_spans(group[0]),
                        ai_generated=False,
                    )
                )
            elif shape == "JE":
                examples.append(
                    Example(
                        japanese=cleaned[0],
                        english=cleaned[1],
                        highlight=_bold_spans(group[0]),
                        ai_generated=False,
                    )
                )
            else:
                skipped.append(
                    {
                        "shape": shape,
                        "reason": UNPAIRED_REASON,
                        "text": " ".join(cleaned),
                    }
                )

    return examples, skipped


def _lesson_url(relative_path: str) -> str:
    """The canonical yoku.bi page for a locked ``src/...`` lesson path.

    mdBook renders ``src/Section1/Part1/Lesson1.md`` at
    ``https://yoku.bi/Section1/Part1/Lesson1.html``.
    """
    page = relative_path
    if page.startswith("src/"):
        page = page[len("src/") :]
    if page.endswith(".md"):
        page = page[: -len(".md")] + ".html"
    return SITE + page


def _lesson_h1(body: str) -> str:
    """The lesson's own authoritative H1 title, or ``""`` when it has none."""
    match = _H1.search(body)
    return match.group(1).strip() if match else ""


def _lesson_prose(body: str) -> str:
    """The lesson's explanatory prose: its Markdown paragraphs, with the H1,
    ``<pre>`` example blocks, and raw block-level HTML removed.

    This is carried verbatim as the point ``explanation`` — Yokubi's own words,
    never a generated summary.
    """
    without_pre = _PRE_BLOCK.sub("", body)
    without_divs = re.sub(r"<div\b.*?</div>", "", without_pre, flags=re.S | re.I)
    lines: list[str] = []
    for line in without_divs.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("<") and stripped.endswith(">"):
            continue
        lines.append(strip_inline_markup(stripped))
    return "\n".join(lines).strip()


def _iter_summary_lessons(summary_text: str):
    """Yield ``(number, label_title, relative_path)`` for each lesson listed in
    ``SUMMARY.md`` that names a numbered ``Lesson<N>.md`` page, in order."""
    for label, href in _SUMMARY_ENTRY.findall(summary_text):
        number_match = _LESSON_NUMBER.search(href)
        if not number_match:
            continue
        relative = href.lstrip("./")
        if not relative.startswith("src/"):
            relative = "src/" + relative
        # The SUMMARY label carries "Lesson N: <title>"; the lesson's own H1 is
        # authoritative, so the label title is only a fallback used if a lesson
        # ever lacked an H1.
        label_title = label.split(":", 1)[1].strip() if ":" in label else label.strip()
        yield int(number_match.group(1)), label_title, relative


@register_extractor
class YokubiExtractor(Extractor):
    """Extract one grammar point per title-declared headword from Yokubi.

    Every file read must appear in the source lock, so a partial corpus fails
    closed rather than silently yielding fewer entries. Each emitted point
    carries the source attribution, the pinned revision, and the lesson URL,
    and its examples are only those whose text actually contains the headword.
    """

    name = "yokubi"
    label = YOKUBI_ATTRIBUTION
    ai_generated_source = False

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)
        revision = self._revision()

        summary = self.read_locked_bytes("src/SUMMARY.md").decode("utf-8")

        points: list[GrammarPoint] = []
        consumed: dict[str, str] = {"src/SUMMARY.md": "index"}
        skipped_lessons: list[dict[str, object]] = []
        covered_lessons: list[dict[str, object]] = []
        lessons_listed = 0
        examples_unattached = 0
        example_skips: list[dict[str, object]] = []

        for number, label_title, relative in _iter_summary_lessons(summary):
            lessons_listed += 1
            # Fails closed: read_locked_bytes raises SourceLockError when a
            # SUMMARY-listed lesson is missing from the lock or its bytes drifted.
            body = self.read_locked_bytes(relative).decode("utf-8")
            consumed[relative] = "lesson"

            title = _lesson_h1(body) or label_title
            heads = title_headwords(title)
            examples, group_skips = parse_examples(body)
            lesson_url = _lesson_url(relative)
            # Attribute each unparseable group to the lesson that declared it, so
            # the coverage report can name where a skip happened instead of
            # publishing an unattributable flat list.
            for skip in group_skips:
                skip["lesson"] = number
                skip["lessonUrl"] = lesson_url
            example_skips.extend(group_skips)
            # An unparseable group that still carries Japanese is lesson-scoped
            # context Yokubi declared but that attaches to no headword; it is
            # counted as unattached rather than silently discarded.
            unparseable_jp = sum(
                1 for g in group_skips if "J" in str(g["shape"]) or "M" in str(g["shape"])
            )

            if not heads:
                skipped_lessons.append(
                    {
                        "lesson": number,
                        "title": title,
                        "lessonUrl": lesson_url,
                        "reason": LESSON_ONLY_REASON,
                    }
                )
                # Every example in a headword-less lesson is lesson-scoped
                # context that attaches to no point.
                examples_unattached += len(examples) + unparseable_jp
                continue

            attached_any = [False] * len(examples)
            for head in heads:
                attached: list[Example] = []
                for idx, example in enumerate(examples):
                    if head in example.japanese:
                        attached.append(example)
                        attached_any[idx] = True
                points.append(
                    GrammarPoint(
                        source=self.name,
                        source_id=f"lesson-{number}:{head}",
                        expression=head,
                        explanation=_lesson_prose(body) or None,
                        examples=tuple(attached),
                        provenance={
                            "lesson": number,
                            "lessonTitle": title,
                            "lessonUrl": lesson_url,
                            "attribution": YOKUBI_ATTRIBUTION,
                            "revision": revision,
                        },
                    )
                )
            examples_unattached += sum(1 for hit in attached_any if not hit) + unparseable_jp
            covered_lessons.append(
                {
                    "lesson": number,
                    "title": title,
                    "lessonUrl": lesson_url,
                    "headwords": list(heads),
                    "examplesAttached": sum(1 for hit in attached_any if hit),
                    "exampleGroupsSkipped": len(group_skips),
                }
            )

        stats: dict[str, object] = {
            "lessonsListed": lessons_listed,
            "headwordPoints": len(points),
            "coveredLessons": covered_lessons,
            "coveredCount": len(covered_lessons),
            "skippedLessons": skipped_lessons,
            "skippedCount": len(skipped_lessons),
            "examplesUnattached": examples_unattached,
            "exampleGroupsSkipped": example_skips,
            "attribution": YOKUBI_ATTRIBUTION,
            "revision": revision,
        }
        result = ExtractResult(
            source=self.name, points=points, consumed=consumed, stats=stats
        )
        # Emit the reviewable per-source artifacts the card requires: the
        # normalized records as JSONL and the coverage report naming every lesson
        # covered or skipped. render_coverage fails closed if the two lesson
        # lists do not account for every lesson SUMMARY.md listed, so a report
        # that silently dropped a lesson cannot be written.
        self.write_jsonl(points)
        self.write_coverage(result)
        return result

    def _revision(self) -> str:
        """The pinned upstream revision recorded in the source lock.

        The lock's top-level ``revision`` is metadata beside the per-file digest
        map that :func:`load_source_lock` shape-checks, so it is read straight
        from the raw lock rather than through the digest loader.
        """
        raw = (self.input_dir / "SOURCE.lock.json").read_text(encoding="utf-8")
        payload = load_json(raw)
        revision = payload.get("revision") if isinstance(payload, dict) else None
        if not isinstance(revision, str) or not revision.strip():
            raise SourceLockError("yokubi source lock records no revision")
        return revision

    def write_jsonl(self, points: list[GrammarPoint]) -> pathlib.Path:
        """Write this source's normalized records as JSONL beside its locked bytes.

        One canonical JSON object per line, in extraction order, matching the
        community sources' ``points.jsonl`` convention so a reviewer can read
        Yokubi's records without running the merge stage.
        """
        from ..pipeline import point_to_json

        path = self.input_dir / JSONL_NAME
        path.write_text(
            "".join(dump_json(point_to_json(point)) + "\n" for point in points),
            encoding="utf-8",
        )
        return path

    def write_coverage(self, result: ExtractResult) -> pathlib.Path:
        """Write the human-readable coverage report the card requires.

        Every lesson ``SUMMARY.md`` lists appears exactly once, either as covered
        with the headwords its own title declared, or as skipped with the reason
        recorded. Unparseable example groups are reported the same way, attributed
        to the lesson that declared them.
        """
        path = self.input_dir / COVERAGE_NAME
        path.write_text(render_coverage(result), encoding="utf-8")
        return path


def render_coverage(result: ExtractResult) -> str:
    """Render the Yokubi coverage report from one extraction result.

    Fails closed rather than publishing an unaccounted lesson: covered plus
    skipped must equal the number of lessons ``SUMMARY.md`` listed, because a
    report that silently loses a lesson is exactly the omission this card forbids.
    """
    stats = result.stats
    listed = int(stats["lessonsListed"])  # type: ignore[arg-type]
    covered: list[dict] = list(stats["coveredLessons"])  # type: ignore[arg-type]
    skipped: list[dict] = list(stats["skippedLessons"])  # type: ignore[arg-type]
    groups: list[dict] = list(stats["exampleGroupsSkipped"])  # type: ignore[arg-type]

    if len(covered) + len(skipped) != listed:
        raise MalformedPayload(
            f"yokubi coverage does not account for every lesson: "
            f"{len(covered)} covered + {len(skipped)} skipped != {listed} listed"
        )

    lines: list[str] = []
    lines.append("# Yokubi coverage report")
    lines.append("")
    lines.append(f"Source: {YOKUBI_ATTRIBUTION}")
    lines.append(f"Upstream revision: `{stats['revision']}`")
    lines.append("")
    lines.append(
        "Yokubi publishes one `# ` H1 per lesson and no sub-headings, so the "
        "smallest unit it declares is the lesson. A headword is only taken from a "
        "Japanese token a lesson title itself declares, and an example only "
        "attaches to a headword when the example text contains it. No grammar-point "
        "boundary is inferred anywhere in this report."
    )
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Lessons listed in `SUMMARY.md`: **{listed}**")
    lines.append(f"- Lessons covered: **{len(covered)}**")
    lines.append(f"- Lessons skipped (reason recorded below): **{len(skipped)}**")
    lines.append(f"- Grammar points emitted: **{len(result.points)}**")
    lines.append(f"- Example sentences unattached to any headword: **{stats['examplesUnattached']}**")
    lines.append(f"- Example groups skipped as unpaired: **{len(groups)}**")
    lines.append("")

    lines.append("## Covered lessons")
    lines.append("")
    lines.append("| Lesson | Title | Headwords declared by the title | Examples attached |")
    lines.append("| --- | --- | --- | --- |")
    for row in covered:
        heads = ", ".join(f"`{head}`" for head in row["headwords"])
        lines.append(
            f"| {row['lesson']} | [{row['title']}]({row['lessonUrl']}) | {heads} "
            f"| {row['examplesAttached']} |"
        )
    lines.append("")

    lines.append("## Skipped lessons")
    lines.append("")
    if not skipped:
        lines.append("None: every lesson declared at least one Japanese headword.")
    else:
        lines.append(
            "These lessons are real Yokubi content, but their own titles declare no "
            "Japanese form, and Yokubi publishes no sub-heading that would draw a "
            "lookupable boundary inside them. They are reported here rather than "
            "segmented by guesswork."
        )
        lines.append("")
        lines.append("| Lesson | Title | Reason |")
        lines.append("| --- | --- | --- |")
        for row in skipped:
            lines.append(
                f"| {row['lesson']} | [{row['title']}]({row['lessonUrl']}) | {row['reason']} |"
            )
    lines.append("")

    lines.append("## Skipped example groups")
    lines.append("")
    if not groups:
        lines.append("None: every example group parsed as a source-paired sentence.")
    else:
        lines.append(
            "An example group whose lines are not a source-paired Japanese sentence "
            "(a conjugation or vocabulary table, or an English-only aside). No "
            "translation or pairing is invented for these; the shape column records "
            "the per-line classification (`J` Japanese, `E` English, `M` mixed)."
        )
        lines.append("")
        lines.append("| Lesson | Shape | Text | Reason |")
        lines.append("| --- | --- | --- | --- |")
        for row in groups:
            text = str(row["text"]).replace("|", "\\|")
            if len(text) > 120:
                text = text[:117] + "..."
            lines.append(f"| {row['lesson']} | `{row['shape']}` | {text} | {row['reason']} |")
    lines.append("")

    return "\n".join(lines)


__all__ = [
    "YOKUBI_ATTRIBUTION",
    "LESSON_ONLY_REASON",
    "UNPAIRED_REASON",
    "SITE",
    "JSONL_NAME",
    "COVERAGE_NAME",
    "strip_inline_markup",
    "title_headwords",
    "parse_examples",
    "render_coverage",
    "YokubiExtractor",
]
