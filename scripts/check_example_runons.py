#!/usr/bin/env python3
"""Measure example-sentence run-ons in the built dictionary ZIP.

A run-on is an example `<li>` (Yomitan structured-content node with
`data == {"example": ""}`) whose JOINED Japanese text contains two or more
sentence-final marks (。 ！ ？) that are each IMMEDIATELY FOLLOWED by more
Japanese (kana/kanji) -- i.e. a new sentence starts right after -- while the
node carries ZERO `br` tags. Such a node renders as several sentences mashed
into one line under the `white-space: pre-line` example CSS.

The measure deliberately reads only the Japanese `span` (`data.ja`), so a `。`
followed by the English translation is never counted. It reports the count and,
with --list, prints residual nodes so ambiguous cases can be characterised.

Usage:
    python scripts/check_example_runons.py [dist/bees-ultimate-grammar-dictionary.zip] [--list N]
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

DEFAULT_ZIP = "dist/bees-ultimate-grammar-dictionary.zip"

# A sentence-final mark that is immediately followed by more Japanese text
# (kana or kanji), i.e. a new sentence begins. Trailing marks (end of field) and
# marks followed by a non-Japanese char (space, English, digit) do not match.
_KANA_KANJI = r"\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff\uf900-\ufaff"
_SENTENCE_BOUNDARY = re.compile(rf"[。！？](?=[{_KANA_KANJI}])")


def _iter_nodes(node):
    """Yield every dict node in a structured-content tree."""
    if isinstance(node, dict):
        yield node
        yield from _iter_nodes(node.get("content"))
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _text_of(node) -> str:
    """Concatenate all leaf strings under a node."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return _text_of(node.get("content"))
    if isinstance(node, list):
        return "".join(_text_of(item) for item in node)
    return ""


def _has_tag(node, tag: str) -> bool:
    for sub in _iter_nodes(node):
        if sub.get("tag") == tag:
            return True
    return False


def _is_example_li(node) -> bool:
    return (
        isinstance(node, dict)
        and node.get("tag") == "li"
        and node.get("data") == {"example": ""}
    )


def _japanese_span(li):
    """The Japanese span inside an example li (data.ja), or None."""
    for sub in _iter_nodes(li.get("content")):
        if sub.get("tag") == "span" and sub.get("data") == {"ja": ""}:
            return sub
    return None


def _all_boundaries_quoted(text: str) -> bool:
    """True if every sentence boundary in ``text`` sits inside a quote/paren.

    Such a node is not a real run-on: the `。` is internal to a quoted utterance
    (`「…。…」`) or a parenthetical gloss (`（…。…）`), which the renderer
    deliberately leaves unsplit.
    """
    depth = 0
    opens, closes = "「『（(", "」』）)"
    for i, ch in enumerate(text):
        if ch in opens:
            depth += 1
        elif ch in closes and depth:
            depth -= 1
        elif ch in "。！？" and i + 1 < len(text) and re.match(
            rf"[{_KANA_KANJI}]", text[i + 1]
        ):
            if depth == 0:
                return False
    return True


def measure(zip_path: str):
    runons = []
    with zipfile.ZipFile(zip_path) as z:
        banks = sorted(n for n in z.namelist() if re.fullmatch(r"term_bank_\d+\.json", n))
        for bank in banks:
            data = json.loads(z.read(bank))
            for entry in data:
                # entry[5] is the glossary (list of structured-content wrappers)
                for glossary in entry[5]:
                    for node in _iter_nodes(glossary):
                        if not _is_example_li(node):
                            continue
                        ja = _japanese_span(node)
                        if ja is None:
                            continue
                        text = _text_of(ja)
                        boundaries = _SENTENCE_BOUNDARY.findall(text)
                        # Only the Japanese span is examined for br, since that is
                        # where a sentence split would land.
                        if len(boundaries) >= 2 and not _has_tag(ja, "br"):
                            runons.append((entry[0], text))
    return runons


def main() -> int:
    args = [a for a in sys.argv[1:]]
    list_n = 0
    if "--list" in args:
        i = args.index("--list")
        list_n = int(args[i + 1]) if i + 1 < len(args) else 20
        del args[i : i + 2]
    zip_path = args[0] if args else DEFAULT_ZIP
    if not Path(zip_path).exists():
        print(f"ZIP not found: {zip_path}", file=sys.stderr)
        return 2
    runons = measure(zip_path)
    quoted = [r for r in runons if _all_boundaries_quoted(r[1])]
    real = [r for r in runons if not _all_boundaries_quoted(r[1])]
    print(f"example run-on nodes (>=2 JA sentence boundaries, 0 br): {len(runons)}")
    print(f"  of which every boundary is inside a quote/paren (NOT a real run-on): {len(quoted)}")
    print(f"  REAL run-ons (a splittable boundary outside any quote): {len(real)}")
    for term, text in real[:list_n]:
        print(f"  REAL [{term}] {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
