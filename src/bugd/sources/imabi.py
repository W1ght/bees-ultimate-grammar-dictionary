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

Redistribution: the IMABI authors granted this build permission to redistribute
the full lesson content with attribution (see `data/sources/imabi/PERMISSION.json`),
so records carry `licenseTier: "A"`, `redistributable: True`, and an attribution
string crediting IMABI (imabi.net), encoded in `provenance` the same way the
other source modules record redistribution posture.
"""

from __future__ import annotations

import html
import re

from ..jsonio import load_json
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock
from .registry import register_extractor

#: Site-meta pages excluded from the lesson spine (matched by slug).
META_SLUGS = {"contact", "about", "about-2"}
META_SLUG_PREFIX = ("table-of-contents", "privacy-policy", "sitemap")

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


@register_extractor
class ImabiExtractor(Extractor):
    """One grammar point per IMABI lesson page."""

    name = "imabi"
    label = "IMABI"
    license_tier = "A"
    redistributable = True

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
        excluded = 0
        zero_example_lessons = 0
        total_examples = 0

        for relative_path in page_files:
            # Fail closed: read_locked_bytes raises if the page is missing from
            # disk or its bytes no longer match the lock.
            raw = self.read_locked_bytes(relative_path)
            consumed[relative_path] = lock[relative_path]["sha256"]

            page = load_json(raw.decode("utf-8"))
            slug = page.get("slug", "")
            if slug in META_SLUGS or slug.startswith(META_SLUG_PREFIX):
                excluded += 1
                continue

            title = html.unescape(page["title"]["rendered"]).strip()
            if not title:
                # A lesson with no headword cannot be a lookup entry.
                excluded += 1
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
            if not examples:
                zero_example_lessons += 1

            provenance: dict[str, object] = {
                "sourceLabel": self.label,
                "attribution": ATTRIBUTION,
                "licenseTier": self.license_tier,
                "redistributable": self.redistributable,
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

        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "lockedPages": len(page_files),
                "excludedMetaPages": excluded,
                "points": len(points),
                "totalExamples": total_examples,
                "lessonsWithZeroExamples": zero_example_lessons,
                "licenseTier": self.license_tier,
                "redistributable": self.redistributable,
                "attribution": ATTRIBUTION,
            },
        )


__all__ = [
    "ImabiExtractor",
    "META_SLUGS",
    "META_SLUG_PREFIX",
    "ATTRIBUTION",
    "strip_html",
    "extract_examples",
]
