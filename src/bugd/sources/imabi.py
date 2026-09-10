"""IMABI — imabi.net Japanese grammar lessons.

Source: a WordPress export of the IMABI lesson corpus, captured under
`data/sources/imabi/` as one JSON file per WP page in `pages/*.json`, indexed by
`index.json` and pinned byte-for-byte in `SOURCE.lock.json`. Each lesson page
carries a `title.rendered` headword and a `content.rendered` HTML body; numbered
example sentences appear inline as `12.` / `7a.` lines whose Japanese sits on the
numbered line and whose English translation, when the author supplies one,
follows on the next non-numbered Latin line.

The lesson page is the authoritative unit: one `GrammarPoint` is emitted per
lesson faithfully, with no invented sub-boundaries. Site-meta pages (contact,
about, table-of-contents, privacy-policy, sitemap) are not lessons and are
excluded from the spine.

Only files listed in `SOURCE.lock.json['files']` are read, and each is read
through `read_locked_bytes`, which fails closed if a locked page is missing or
its bytes no longer match the lock.
"""

from __future__ import annotations

import html
import pathlib
import re

from ..jsonio import dump_json, load_json
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock
from .registry import register_extractor

#: Site-meta pages excluded from the lesson spine (matched by slug).
#:
#: Measured against the locked 501-page spine, exactly seven pages carry no
#: lesson content. The first four were already excluded; `style-guide` (a
#: WordPress theme test page whose whole body is "Heading 1 ... This is a
#: quote"), `about-us` (the author's biography) and the site landing page were
#: not, and reached the emitted records as headwords "STYLE GUIDE",
#: "Imabi's Little crew" and "Welcome to IMABI!".
#:
#: The landing page is matched by page id rather than slug: its slug is the
#: percent-encoded Japanese title `%e3%82%88...` (ようこそ、「いまび」へ), which no
#: readable slug rule can match without also risking real Japanese-titled
#: lessons. Its body is a level chooser plus a site-remodel completion
#: percentage, and it is `link` == the site root.
META_SLUGS = {"contact", "about", "about-2", "style-guide", "about-us"}
META_SLUG_PREFIX = ("table-of-contents", "privacy-policy", "sitemap")

#: Site landing page (WP page id), excluded by id — see META_SLUGS.
META_PAGE_IDS = frozenset({11})

#: Per-source JSONL lands beside the locked bytes so a reviewer can read one
#: source's normalized records without running the merge stage. Mirrors the
#: community sources' `points.jsonl` convention.
JSONL_NAME = "points.jsonl"

#: Human-readable report naming every locked page as imported or skipped.
COVERAGE_NAME = "COVERAGE.md"

#: Attribution rendered on merged IMABI entries.
ATTRIBUTION = "IMABI (imabi.net)"

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_BLOCK_END = re.compile(r"</(p|h[1-6]|li|tr|div|figcaption|blockquote)>", re.I)
_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
#: A numbered example line: "12.", "7a.", full-width period tolerated.
_EXNUM = re.compile(r"^\s*(\d+[a-z]?)[.\uff0e]\s*(.*)$")
_LATIN = re.compile(r"[A-Za-z]")


def strip_html(content: str) -> str:
    """Flatten a WP `content.rendered` body to newline-delimited text."""
    content = _BR.sub("\n", content)
    content = _BLOCK_END.sub("\n", content)
    content = _TAG.sub("", content)
    return html.unescape(content)


def extract_examples(text: str) -> list[tuple[str, str | None]]:
    """Pair numbered CJK lines with a following English translation line.

    A numbered line whose body contains CJK is a Japanese example. When the next
    non-empty line is a Latin-only, non-numbered line it is taken as the English
    translation for the accumulated Japanese line(s); otherwise the Japanese is
    kept without a translation. Consecutive numbered Japanese lines that share a
    single following translation all receive it.
    """
    lines = [line.strip() for line in text.split("\n")]
    examples: list[tuple[str, str | None]] = []
    pending: list[str] = []

    def is_num(line: str):
        match = _EXNUM.match(line)
        return match if (match and _CJK.search(match.group(2))) else None

    i = 0
    while i < len(lines):
        match = is_num(lines[i])
        if match:
            pending.append(match.group(2).strip())
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines) and lines[j] and not is_num(lines[j]):
                nxt = lines[j]
                if _LATIN.search(nxt) and not _CJK.search(nxt):
                    for jp_text in pending:
                        examples.append((jp_text, nxt))
                    pending.clear()
                    i = j
                    continue
                for jp_text in pending:
                    examples.append((jp_text, None))
                pending.clear()
        i += 1
    for jp_text in pending:
        examples.append((jp_text, None))
    return examples


def skip_reason(page_id: int, slug: str, title: str) -> str | None:
    """Why this locked page is not an importable lesson, or None if it is.

    One function so the reported reason and the exclusion decision can never
    disagree: the coverage report is rendered from the same values the loop
    used to skip.
    """
    if page_id in META_PAGE_IDS:
        return "site landing page, not a lesson"
    if slug in META_SLUGS or slug.startswith(META_SLUG_PREFIX):
        return "site-meta page, not a lesson"
    if not title:
        return "no headword: the page title is empty"
    return None


@register_extractor
class ImabiExtractor(Extractor):
    """One grammar point per IMABI lesson page."""

    name = "imabi"
    label = "IMABI"

    def _lesson_files(self, lock: dict[str, dict]) -> list[str]:
        """Locked `pages/*.json` files, ordered by page id."""
        return sorted(
            (path for path in lock if path.startswith("pages/") and path.endswith(".json")),
            key=lambda path: int(path.split("/")[1].split(".")[0]),
        )

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)
        page_files = self._lesson_files(lock)

        points: list[GrammarPoint] = []
        consumed: dict[str, str] = {}
        skips: list[dict[str, object]] = []
        zero_example_lessons = 0
        total_examples = 0
        examples_with_english = 0

        for relative_path in page_files:
            # Fail closed: read_locked_bytes raises if the page is missing from
            # disk or its bytes no longer match the lock.
            raw = self.read_locked_bytes(relative_path)
            consumed[relative_path] = lock[relative_path]["sha256"]

            page = load_json(raw.decode("utf-8"))
            slug = page.get("slug", "")
            page_id = page["id"]
            title = html.unescape(page["title"]["rendered"]).strip()

            reason = skip_reason(page_id, slug, title)
            if reason is not None:
                skips.append(
                    {"pageId": page_id, "slug": slug, "title": title, "reason": reason}
                )
                continue

            body = strip_html(page["content"]["rendered"])
            explanation = "\n".join(
                line.strip() for line in body.split("\n") if line.strip()
            ).strip()

            examples = tuple(
                Example(japanese=japanese, english=english)
                for japanese, english in extract_examples(body)
            )
            total_examples += len(examples)
            examples_with_english += sum(1 for ex in examples if ex.english)
            if not examples:
                zero_example_lessons += 1

            provenance: dict[str, object] = {
                "sourceLabel": self.label,
                "attribution": ATTRIBUTION,
                "pageId": page["id"],
                "slug": slug,
            }
            link = page.get("link")
            if link:
                provenance["lessonUrl"] = link

            points.append(
                GrammarPoint(
                    source=self.name,
                    source_id=str(page["id"]),
                    expression=title,
                    explanation=explanation or None,
                    examples=examples,
                    provenance=provenance,
                )
            )

        result = ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "lockedPages": len(page_files),
                "importedLessons": len(points),
                "points": len(points),
                "skippedPages": len(skips),
                "skips": skips,
                "skipReasonCounts": _reason_counts(skips),
                "totalExamples": total_examples,
                "examplesWithEnglish": examples_with_english,
                "lessonsWithZeroExamples": zero_example_lessons,
                "attribution": ATTRIBUTION,
            },
        )
        # The card's two reviewable deliverables, written by the production
        # extract path rather than a side script, so an artifact on disk can
        # only ever be the one this extractor actually produced.
        self.write_jsonl(points)
        self.write_coverage(result, len(page_files))
        return result


    def write_jsonl(self, points: list[GrammarPoint]) -> pathlib.Path:
        """Write this source's normalized records as JSONL beside its bytes."""
        from ..pipeline import point_to_json

        path = self.input_dir / JSONL_NAME
        path.write_text(
            "".join(dump_json(point_to_json(point)) + "\n" for point in points),
            encoding="utf-8",
        )
        return path

    def write_coverage(self, result: ExtractResult, locked_pages: int) -> pathlib.Path:
        """Write the report naming every locked page imported or skipped."""
        path = self.input_dir / COVERAGE_NAME
        path.write_text(render_coverage(result, locked_pages), encoding="utf-8")
        return path


def _reason_counts(skips: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for skip in skips:
        reason = str(skip["reason"])
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def render_coverage(result: ExtractResult, locked_pages: int) -> str:
    """Render IMABI's coverage report from one extraction result.

    Fails closed when imported + skipped does not equal the locked pages read,
    so a report that silently lost a page cannot be written.
    """
    stats = result.stats
    imported = int(stats["importedLessons"])
    skips: list[dict[str, object]] = list(stats["skips"])  # type: ignore[arg-type]
    if imported + len(skips) != locked_pages:
        raise ValueError(
            "imabi coverage does not account for every locked page: "
            f"{imported} imported + {len(skips)} skipped != {locked_pages} locked"
        )

    lines = [
        "# IMABI coverage report",
        "",
        f"Locked pages read: {locked_pages}",
        f"Lessons imported: {imported}",
        f"Pages skipped: {len(skips)}",
        f"Example sentences: {stats['totalExamples']} "
        f"({stats['examplesWithEnglish']} with an author-supplied English translation)",
        f"Imported lessons carrying no numbered example: {stats['lessonsWithZeroExamples']}",
        "",
        f"Attribution: {stats['attribution']}",
        "",
        "## Skipped pages, with reasons",
        "",
    ]
    for reason, count in _reason_counts(skips).items():
        lines.append(f"* {count} x {reason}")
    lines.append("")
    lines.append("| page id | title | slug | reason |")
    lines.append("| --- | --- | --- | --- |")
    for skip in sorted(skips, key=lambda s: int(s["pageId"])):  # type: ignore[arg-type]
        title = str(skip["title"]).replace("|", "\\|") or "(no title)"
        lines.append(
            f"| {skip['pageId']} | {title} | {skip['slug']} | {skip['reason']} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "ImabiExtractor",
    "META_SLUGS",
    "META_SLUG_PREFIX",
    "META_PAGE_IDS",
    "JSONL_NAME",
    "COVERAGE_NAME",
    "ATTRIBUTION",
    "strip_html",
    "extract_examples",
    "skip_reason",
    "render_coverage",
]
