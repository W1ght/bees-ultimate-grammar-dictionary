"""HJGP 日本語文型辞典 — monolingual Japanese grammar dictionary.

Source: HuangAntimony/Nihongo-Bunkei-Jiten, a rebuild of the Japanese grammar
dictionary from mefat.review. 1,245 Yomitan structured-content entries with
rich furigana, structured senses/subsenses, examples, and explanations.

This is a plain ``Extractor`` rather than a ``CommunityBankExtractor`` because
the producer's structured content uses ``data-role`` attributes for semantic
blocks, which the generic text flattener cannot usefully parse. The extractor
walks the structured content tree directly.

Semantic roles in the structured content:

    entry → meta (表記/読み/接続), preface, sense-list → sense-item →
      sense-title, block(explains), block(examples) → example-line,
      block(keyword), subsense, pattern-list → pattern-item, reference-line
"""

from __future__ import annotations

import json
import re

from ..jsonio import MalformedPayload
from ..model import Example, GrammarPoint
from .base import Extractor, ExtractResult, load_source_lock, write_points_jsonl
from .community import clean
from .registry import register_extractor

_XREF = re.compile(r"[⇾→]\s*【?\s*([^】\n]+?)\s*】?")
_SENTENCE_NUM = re.compile(r"^[①-⑳㉑-㊿]\s*")
_FRONT_MATTER = frozenset(
    {"0Index of meaning and function groups", "0Preface", "0User's Guide"}
)
_TERM_ROW_LENGTH = 8


def _text_of(node: object) -> str:
    """Extract plain text, stripping ruby readings."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_text_of(child) for child in node)
    if isinstance(node, dict):
        tag = node.get("tag")
        if tag in ("rt", "rp"):
            return ""
        if tag == "br":
            return "\n"
        content = node.get("content")
        if content is not None:
            return _text_of(content)
    return ""


def _role(node: object) -> str | None:
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            return data.get("role")
    return None


def _kind(node: object) -> str | None:
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            return data.get("kind")
    return None


def _children(node: object) -> list:
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, list):
            return content
        if content is not None:
            return [content]
    if isinstance(node, list):
        return node
    return []


def _walk_examples(node: object) -> list[str]:
    """Collect example sentences from example blocks."""
    sentences: list[str] = []
    for child in _children(node):
        if _role(child) == "example-line":
            text = _text_of(child).strip()
            text = _SENTENCE_NUM.sub("", text).strip()
            if text:
                sentences.append(text)
        elif isinstance(child, (dict, list)):
            sentences.extend(_walk_examples(child))
    return sentences


def _walk_explains(node: object) -> list[str]:
    """Collect explanation text from explain blocks."""
    parts: list[str] = []
    for child in _children(node):
        role = _role(child)
        if role == "block-heading":
            continue
        if role == "block-body":
            text = _text_of(child).strip()
            if text:
                parts.append(text)
        elif isinstance(child, (dict, list)):
            parts.extend(_walk_explains(child))
    if not parts:
        text = _text_of(node).strip()
        label_text = ""
        for child in _children(node):
            if _role(child) == "block-heading":
                label_text = _text_of(child).strip()
        remaining = text
        if label_text and remaining.startswith(label_text):
            remaining = remaining[len(label_text):].strip()
        if remaining:
            parts = [remaining]
    return parts


def _walk_sense(node: object) -> tuple[str | None, list[str], list[Example], list[str]]:
    """Walk one sense-item: (title, explanations, examples, patterns)."""
    title: str | None = None
    explanations: list[str] = []
    examples: list[Example] = []
    patterns: list[str] = []

    for child in _children(node):
        role = _role(child)
        if role == "sense-title":
            title = _text_of(child).strip() or None
        elif role == "subsense-title":
            text = _text_of(child).strip()
            if text:
                explanations.append(text)
        elif role in ("block",):
            kind_val = _kind(child)
            if kind_val == "examples":
                for sentence in _walk_examples(child):
                    examples.append(Example(japanese=sentence))
            elif kind_val in ("explains", "keyword"):
                explanations.extend(_walk_explains(child))
        elif role == "subsense":
            _, sub_exp, sub_ex, sub_pat = _walk_sense(child)
            explanations.extend(sub_exp)
            examples.extend(sub_ex)
            patterns.extend(sub_pat)
        elif role == "pattern-list":
            for item in _children(child):
                if _role(item) == "pattern-item":
                    text = _text_of(item).strip()
                    if text:
                        patterns.append(text)
        elif role == "reference-line":
            text = _text_of(child).strip()
            if text:
                explanations.append(text)
        elif isinstance(child, (dict, list)) and role not in (
            "meta", "preface", "meta-line", "meta-label",
            "block-heading", "block-body", "block-label",
            "example-line", "example-header", "pattern-item",
        ):
            kind_val = _kind(child)
            if kind_val == "examples":
                for sentence in _walk_examples(child):
                    examples.append(Example(japanese=sentence))
            elif kind_val in ("explains", "keyword"):
                explanations.extend(_walk_explains(child))
            elif not kind_val:
                _, sub_exp, sub_ex, sub_pat = _walk_sense(child)
                explanations.extend(sub_exp)
                examples.extend(sub_ex)
                patterns.extend(sub_pat)

    return title, explanations, examples, patterns


def _parse_entry(sc: object) -> tuple[
    str | None, str | None, list[str], list[Example], list[str]
]:
    """Parse structured content: (meta_kanji, meta_reading, exps, exs, structs)."""
    meta_kanji: str | None = None
    meta_reading: str | None = None
    all_explanations: list[str] = []
    all_examples: list[Example] = []
    all_structures: list[str] = []

    for child in _children(sc):
        role = _role(child)

        if role == "meta":
            for meta_child in _children(child):
                if _role(meta_child) == "meta-line":
                    text = _text_of(meta_child).strip()
                    if "表記" in text:
                        val = re.sub(r"^表記[：:]\s*", "", text).strip()
                        if val:
                            meta_kanji = val
                    elif "読み" in text:
                        val = re.sub(r"^読み[：:]\s*", "", text).strip()
                        if val:
                            meta_reading = val
            continue

        if role == "preface":
            text = _text_of(child).strip()
            if text:
                all_explanations.insert(0, text)
            continue

        if role == "sense-list":
            for item in _children(child):
                if _role(item) == "sense-item":
                    title, exps, exs, pats = _walk_sense(item)
                    if title:
                        all_structures.append(title)
                    all_explanations.extend(exps)
                    all_examples.extend(exs)
                    all_structures.extend(pats)
            continue

        if role == "sense-item":
            title, exps, exs, pats = _walk_sense(child)
            if title:
                all_structures.append(title)
            all_explanations.extend(exps)
            all_examples.extend(exs)
            all_structures.extend(pats)
            continue

        if role == "entry" or (isinstance(child, dict) and not role):
            mk, mr, exps, exs, structs = _parse_entry(child)
            if mk and not meta_kanji:
                meta_kanji = mk
            if mr and not meta_reading:
                meta_reading = mr
            all_explanations.extend(exps)
            all_examples.extend(exs)
            all_structures.extend(structs)

    return meta_kanji, meta_reading, all_explanations, all_examples, all_structures


@register_extractor
class HjgpExtractor(Extractor):
    name = "hjgp"
    label = "日本語文型辞典"

    def extract(self) -> ExtractResult:
        lock = load_source_lock(self.input_dir)

        bank_raw = self.read_locked_bytes("term_bank_1.json")
        consumed = {"term_bank_1.json": lock["term_bank_1.json"]["sha256"]}

        # Also verify the other locked files exist
        for name in lock:
            if name != "term_bank_1.json":
                self.read_locked_bytes(name)
                consumed[name] = lock[name]["sha256"]

        rows = json.loads(bank_raw)
        if not isinstance(rows, list):
            raise MalformedPayload("hjgp term bank must be a JSON array")

        points: list[GrammarPoint] = []
        skipped = 0
        with_examples = 0
        with_meaning = 0

        for row in rows:
            if not isinstance(row, list) or len(row) != _TERM_ROW_LENGTH:
                raise MalformedPayload("hjgp: malformed term row")

            expression = row[0]
            if not isinstance(expression, str) or not expression.strip():
                continue

            if expression in _FRONT_MATTER:
                skipped += 1
                continue

            reading = row[1] if isinstance(row[1], str) else ""
            sequence = row[6] if isinstance(row[6], int) else 0
            term_tags = row[7] if isinstance(row[7], str) else ""

            glossary = row[5]
            if not isinstance(glossary, list) or not glossary:
                skipped += 1
                continue

            sc = None
            flat_text = ""
            for item in glossary:
                if isinstance(item, dict) and item.get("type") == "structured-content":
                    sc = item.get("content")
                elif isinstance(item, str):
                    flat_text += item

            if not sc and not flat_text:
                skipped += 1
                continue

            # Check for cross-reference
            if not sc:
                text = flat_text.strip()
            else:
                text = _text_of(sc).strip()

            xref = _XREF.search(text)
            if xref and len(text) < 120:
                target = xref.group(1).strip().strip("【】")
                points.append(
                    GrammarPoint(
                        source=self.name,
                        source_id=str(sequence) if sequence else expression,
                        expression=expression,
                        reading=clean(reading) or expression,
                        provenance={
                            "sourceLabel": self.label,
                            "aliasOf": target,
                        },
                    )
                )
                continue

            meta_kanji = None
            meta_reading = None
            explanations: list[str] = []
            examples: list[Example] = []
            structures: list[str] = []

            if sc:
                meta_kanji, meta_reading, explanations, examples, structures = (
                    _parse_entry(sc)
                )

            if not explanations and not examples and flat_text:
                explanations = [flat_text.strip()]

            expr = expression
            if meta_kanji and meta_kanji != expression:
                expr = meta_kanji

            rd = clean(reading) or meta_reading or None
            if rd == expr:
                rd = None

            meaning = clean("\n".join(explanations)) if explanations else None
            structure = clean("\n".join(structures)) if structures else None

            if meaning:
                with_meaning += 1
            if examples:
                with_examples += 1

            provenance: dict[str, object] = {
                "sourceLabel": self.label,
            }
            if term_tags:
                provenance["producerTermTags"] = term_tags

            points.append(
                GrammarPoint(
                    source=self.name,
                    source_id=str(sequence) if sequence else expression,
                    expression=expr,
                    reading=rd,
                    meaning=meaning,
                    structure=structure,
                    examples=tuple(examples),
                    tags=(term_tags,) if term_tags else (),
                    provenance=provenance,
                )
            )

        write_points_jsonl(self.input_dir, points)

        return ExtractResult(
            source=self.name,
            points=points,
            consumed=consumed,
            stats={
                "bankRows": len(rows),
                "points": len(points),
                "skipped": skipped,
                "withExamples": with_examples,
                "withMeaning": with_meaning,
                "withStructure": sum(1 for p in points if p.structure),
            },
        )


__all__ = ["HjgpExtractor"]
