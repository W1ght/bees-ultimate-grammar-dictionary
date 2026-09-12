#!/usr/bin/env python3
"""Scrape nihongokyoshi-net.com for updated JLPT grammar data.

Discovers grammar point URLs from the main index page, then scrapes each page
to extract: headword, meaning, structure, JLPT level, English translations,
explanation, and example sentences (with English translations).

Outputs Yomitan-compatible term banks that the existing ``NihongoNetExtractor``
can parse.

Usage:
    python3 scripts/scrape_nihongokyoshi.py [--delay SECONDS] [--limit N]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "sources" / "nihongo_net"

BASE_URL = "https://nihongokyoshi-net.com"
INDEX_URL = f"{BASE_URL}/jlpt-grammars/"

LEVEL_TAGS = {
    "N1": "日本語NET―N1文法",
    "N2": "日本語NET―N2文法",
    "N3": "日本語NET―N3文法",
    "N4": "日本語NET―N4文法",
    "N5": "日本語NET―N5文法",
}

USER_AGENT = (
    "bees-ultimate-grammar-dictionary/scraper "
    "(+https://github.com/bee-san/bees-ultimate-grammar-dictionary; "
    "educational grammar dictionary project)"
)
TIMEOUT = 30
MAX_RETRIES = 3
DEFAULT_DELAY = 1.5

_HIRAGANA_RANGE = re.compile(r"[ぁ-ゖ]+")
_LEVEL_FROM_URL = re.compile(r"/jlptn([1-5])")


def fetch(url: str, *, delay: float = DEFAULT_DELAY) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                content = response.read().decode("utf-8", errors="replace")
            time.sleep(delay)
            return content
        except (urllib.error.URLError, OSError) as error:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = delay * (attempt + 2)
            print(f"  retry {attempt + 1} for {url}: {error}", file=sys.stderr)
            time.sleep(wait)
    return ""


# ---------------------------------------------------------------------------
# Link discovery from the main index page
# ---------------------------------------------------------------------------

class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append(href)


def discover_all_urls(*, delay: float) -> dict[str, list[str]]:
    """Discover grammar URLs from the main index, grouped by JLPT level."""
    html = fetch(INDEX_URL, delay=delay)
    parser = _LinkExtractor()
    parser.feed(html)

    by_level: dict[str, list[str]] = {}
    seen: set[str] = set()

    for link in parser.links:
        if not link.startswith(BASE_URL):
            continue
        m = _LEVEL_FROM_URL.search(link)
        if not m:
            continue
        # Skip quiz, category, and non-grammar pages
        if "quiz" in link or "category" in link or "tag/" in link:
            continue
        # Grammar pages have a date-based path like /2019/05/07/jlptn1-grammar-xxx/
        if not re.search(r"/\d{4}/\d{2}/\d{2}/", link):
            continue
        normalized = link.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        level = f"N{m.group(1)}"
        by_level.setdefault(level, []).append(link)

    return by_level


# ---------------------------------------------------------------------------
# Content-aware HTML parser for grammar pages
# ---------------------------------------------------------------------------

class _GrammarPageParser(HTMLParser):
    """Parse a grammar page into structured sections and examples.

    The page structure (as of 2026):
        <section class="single-post-main">
          <div class="content">
            <h2>文型：〜headword</h2>
            <div class="sc_frame">  -- contains [意味], [接続], etc.
            <h2>例文</h2>
            <div class="sentence-frame">  -- one per example
              <p>Japanese sentence (with <strong>highlight</strong>)</p>
              <div class="border">...</div>
              <p class="p1">English translation</p>
            </div>
            ... more sentence-frames ...
            <h2>解説</h2> or other sections
    """

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._in_content = False
        self._content_depth = 0
        self._in_title = False
        self._in_h2 = False
        self._in_sentence_frame = False
        self._sentence_depth = 0
        self._in_strong = False
        self._in_p1 = False
        self._skip_script = False

        self._parts: list[str] = []
        self._h2_parts: list[str] = []
        self._sentence_ja_parts: list[str] = []
        self._sentence_en_parts: list[str] = []
        self._strong_parts: list[str] = []
        self._past_border = False

        self.title = ""
        self.sections: dict[str, str] = {}
        self.examples: list[dict[str, str]] = []
        self.bold_in_examples: list[list[str]] = []

        self._current_section: str | None = None
        self._section_parts: list[str] = []
        self._current_example_bolds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        cls = dict(attrs).get("class", "") or ""

        if tag == "script":
            self._skip_script = True
            return

        if tag == "h1" and not self.title:
            self._in_title = True
            self._parts = []

        if "content" == cls.strip() and not self._in_content:
            self._in_content = True
            self._content_depth = self._depth

        if not self._in_content:
            return

        if tag == "h2":
            self._in_h2 = True
            self._h2_parts = []
            self._flush_section()

        if "sentence-frame" in cls:
            self._in_sentence_frame = True
            self._sentence_depth = self._depth
            self._sentence_ja_parts = []
            self._sentence_en_parts = []
            self._past_border = False
            self._current_example_bolds = []

        if self._in_sentence_frame and "border" in cls and tag == "div":
            self._past_border = True

        if self._in_sentence_frame and tag == "p":
            if "p1" in cls or self._past_border:
                self._in_p1 = True
                self._sentence_en_parts = []

        if tag in ("strong", "b"):
            self._in_strong = True
            self._strong_parts = []

        if tag == "br":
            if self._in_sentence_frame:
                if self._in_p1:
                    self._sentence_en_parts.append("\n")
                else:
                    self._sentence_ja_parts.append("\n")
            elif self._in_content and not self._in_h2:
                self._section_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._skip_script = False
            self._depth -= 1
            return

        if self._in_title and tag == "h1":
            self.title = "".join(self._parts).strip()
            self._in_title = False

        if self._in_h2 and tag == "h2":
            h2_text = "".join(self._h2_parts).strip()
            self._in_h2 = False
            self._current_section = h2_text

        if self._in_strong and tag in ("strong", "b"):
            self._in_strong = False
            bold_text = "".join(self._strong_parts).strip()
            if bold_text and self._in_sentence_frame and not self._in_p1:
                self._current_example_bolds.append(bold_text)

        if self._in_sentence_frame and self._depth == self._sentence_depth:
            ja = "".join(self._sentence_ja_parts).strip()
            en = "".join(self._sentence_en_parts).strip()
            if ja:
                self.examples.append({"ja": ja, "en": en or None})
                self.bold_in_examples.append(self._current_example_bolds)
            self._in_sentence_frame = False
            self._in_p1 = False

        if self._in_p1 and tag == "p":
            self._in_p1 = False

        if self._in_content and self._depth == self._content_depth:
            self._flush_section()
            self._in_content = False

        if self._in_content and tag in ("p",) and not self._in_sentence_frame:
            self._section_parts.append("\n")

        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_script:
            return
        if self._in_title:
            self._parts.append(data)
        if self._in_h2:
            self._h2_parts.append(data)
        if self._in_sentence_frame:
            if self._in_p1:
                self._sentence_en_parts.append(data)
            else:
                self._sentence_ja_parts.append(data)
            if self._in_strong:
                self._strong_parts.append(data)
        elif self._in_content and not self._in_h2:
            self._section_parts.append(data)
            if self._in_strong:
                self._strong_parts.append(data)

    def _flush_section(self) -> None:
        if self._current_section is not None:
            text = "".join(self._section_parts).strip()
            if text:
                self.sections[self._current_section] = text
        self._section_parts = []


# ---------------------------------------------------------------------------
# Section text parsing
# ---------------------------------------------------------------------------

_BRACKET_SECTION = re.compile(
    r"\[([^\]]+)\]\s*\n?\s*(.*?)(?=\[|$)", re.S
)

def _parse_info_block(text: str) -> dict[str, str]:
    """Parse the [意味] / [接続] / [英訳] / [JLPT レベル] block."""
    result: dict[str, str] = {}
    for m in _BRACKET_SECTION.finditer(text):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if val:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Structured entry
# ---------------------------------------------------------------------------

def parse_page(url: str, html: str) -> dict | None:
    parser = _GrammarPageParser()
    parser.feed(html)

    if not parser.title:
        return None

    m = _LEVEL_FROM_URL.search(url)
    level = f"N{m.group(1)}" if m else None

    # Extract headword from title
    title = parser.title
    title_match = re.search(r"文法・例文[：:]\s*(.+)", title)
    if title_match:
        expr_display = title_match.group(1).strip()
    else:
        expr_display = re.sub(r"^【[^】]*】\s*", "", title).strip()
        expr_display = re.sub(r"\s*[-|｜].*$", "", expr_display).strip()

    if not expr_display:
        return None

    headword = re.sub(r"^[〜～]+", "", expr_display).strip() or expr_display

    # Parse the info block (first section before 例文)
    info_text = ""
    for key in list(parser.sections):
        # The first h2 is typically 文型：〜xxx — its content has the [意味] etc.
        if "文型" in key or key == expr_display or not info_text:
            info_text = parser.sections.get(key, "")
            break

    info = _parse_info_block(info_text)

    meaning = info.get("意味")
    structure = info.get("接続")
    english = info.get("英訳")
    notes = info.get("備考")

    explanation_parts: list[str] = []
    for key, val in parser.sections.items():
        if "解説" in key:
            explanation_parts.append(val)
    explanation = "\n".join(explanation_parts).strip() or None

    lesson_plan_parts: list[str] = []
    for key, val in parser.sections.items():
        if "教案" in key:
            lesson_plan_parts.append(val)
    lesson_plan = "\n".join(lesson_plan_parts).strip() or None

    if notes:
        explanation = f"{explanation}\n{notes}" if explanation else notes

    return {
        "headword": headword,
        "expression_display": expr_display,
        "level": level,
        "meaning": meaning,
        "structure": structure,
        "english": english,
        "explanation": explanation,
        "lesson_plan": lesson_plan,
        "examples": parser.examples,
        "bold_in_examples": parser.bold_in_examples,
        "url": url,
        "title": title,
    }


# ---------------------------------------------------------------------------
# Term bank output — matches existing aiko-tanaka/NihongoNetExtractor format
# ---------------------------------------------------------------------------

def _reading_for(headword: str) -> str:
    parts = _HIRAGANA_RANGE.findall(headword)
    return "".join(parts) if parts else headword


def entry_to_row(entry: dict) -> list:
    headword = entry["headword"]
    reading = _reading_for(headword)
    level = entry["level"]
    url = entry["url"]

    # Build the text body matching existing section format
    parts: list[str] = []

    title_line = f"【   【JLPT {level}】文法・例文：〜{entry['expression_display']}   】"
    parts.append(title_line)
    parts.append("")
    parts.append("")

    if entry.get("meaning"):
        parts.append("[意味]")
        for line in entry["meaning"].split("\n"):
            parts.append(f" {line.strip()}")
        parts.append("")

    if entry.get("english"):
        parts.append("[英訳]")
        for line in entry["english"].split("\n"):
            parts.append(f" {line.strip()}")
        parts.append("")

    if entry.get("structure"):
        parts.append("[接続]")
        for line in entry["structure"].split("\n"):
            parts.append(f" {line.strip()}")
        parts.append("")

    parts.append("[JLPT レベル]")
    parts.append(f" {level}")
    parts.append("")

    if entry.get("explanation"):
        parts.append("[解説]")
        for line in entry["explanation"].split("\n"):
            parts.append(f" {line.strip()}")
        parts.append("")

    if entry.get("lesson_plan"):
        parts.append("[教案]")
        for line in entry["lesson_plan"].split("\n"):
            parts.append(f" {line.strip()}")
        parts.append("")

    if entry.get("examples"):
        parts.append("")
        parts.append("例文")
        for ex in entry["examples"]:
            ja = ex["ja"]
            parts.append(f"・{ja}")
            if ex.get("en"):
                parts.append(f" {ex['en']}")
        parts.append("")

    text = "\n".join(parts)
    tag = LEVEL_TAGS.get(level, "")
    def_tags = f"・〜{entry['expression_display']}"

    row = [
        headword,
        reading,
        def_tags,
        "",
        0,
        [
            {
                "type": "structured-content",
                "content": [
                    text,
                    {"tag": "a", "href": url, "content": "nihongo kyoushi link"},
                ],
            }
        ],
        0,
        tag,
    ]
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="seconds between requests (default: 1.5)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="limit pages per level (0 = all)",
    )
    args = parser.parse_args(argv)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old banks/index
    for old in OUTPUT_DIR.glob("term_bank_*.json"):
        old.unlink()
    for old in (OUTPUT_DIR / "index.json", OUTPUT_DIR / "changelog.txt"):
        if old.exists():
            old.unlink()

    # Step 1: Discover
    print(f"[scrape] Discovering grammar URLs from {INDEX_URL}")
    by_level = discover_all_urls(delay=args.delay)
    for level in sorted(by_level):
        print(f"  {level}: {len(by_level[level])} URLs")

    # Step 2: Scrape each page
    all_entries: dict[str, list[dict]] = {}
    total = 0
    failed: list[str] = []

    for level in ["N1", "N2", "N3", "N4", "N5"]:
        urls = by_level.get(level, [])
        if args.limit > 0:
            urls = urls[: args.limit]

        entries: list[dict] = []
        for i, url in enumerate(urls):
            total += 1
            print(f"  [{level} {i + 1}/{len(urls)}] {url}")
            try:
                html = fetch(url, delay=args.delay)
                entry = parse_page(url, html)
                if entry:
                    entries.append(entry)
                else:
                    print("    SKIP: could not parse")
                    failed.append(url)
            except Exception as error:
                print(f"    FAIL: {error}")
                failed.append(url)

        all_entries[level] = sorted(entries, key=lambda e: e["headword"])
        print(f"  {level} done: {len(entries)} entries")

    # Step 3: Write term banks — one per level
    bank_num = 0
    total_rows = 0
    for level in ["N1", "N2", "N3", "N4", "N5"]:
        entries = all_entries.get(level, [])
        if not entries:
            continue
        bank_num += 1
        rows = [entry_to_row(e) for e in entries]
        bank_path = OUTPUT_DIR / f"term_bank_{bank_num}.json"
        bank_path.write_text(
            json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        total_rows += len(rows)
        print(f"[scrape] wrote {bank_path.name}: {len(rows)} entries ({level})")

    # Index file
    total_entries = sum(len(v) for v in all_entries.values())
    index = {
        "title": "JLPT文法解説まとめ",
        "revision": f"scraped_{datetime.date.today().isoformat()}",
        "sequenced": False,
        "format": 3,
        "url": INDEX_URL,
        "description": (
            f"JLPT文法解説まとめ — scraped from nihongokyoshi-net.com. "
            f"{total_entries} entries, {datetime.date.today().isoformat()}."
        ),
        "attribution": "日本語NET (nihongokyoshi-net.com)",
        "author": "nihongobongo (scraped by bees-ultimate-grammar-dictionary)",
    }
    (OUTPUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # SOURCE.lock.json
    files: dict[str, dict[str, object]] = {}
    for path in sorted(OUTPUT_DIR.iterdir()):
        if path.name in ("SOURCE.lock.json", "points.jsonl", "scraped_raw.json"):
            continue
        data = path.read_bytes()
        files[path.name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "byteCount": len(data),
        }

    lock = {
        "source": "nihongo_net",
        "acquiredAt": datetime.datetime.now(datetime.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "provenance": {
            "producer": INDEX_URL,
            "method": "scraped",
            "scrapedAt": datetime.date.today().isoformat(),
        },
        "files": files,
    }
    (OUTPUT_DIR / "SOURCE.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Raw data for debugging
    (OUTPUT_DIR / "scraped_raw.json").write_text(
        json.dumps(
            {level: entries for level, entries in all_entries.items()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if failed:
        print(f"\n[scrape] Failed ({len(failed)}):")
        for url in failed:
            print(f"  {url}")

    print(f"\n[scrape] Done. {total_entries} entries, {bank_num} banks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
