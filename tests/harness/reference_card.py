"""Contract-faithful card composition, used until UGD-09's composer lands.

Implements `docs/card-contract.md` exactly:

above the fold, in order
  1. headword row  — expression (`lang="ja"`), kana reading when it differs,
     then JLPT badge(s) when at least one source assigns a level;
  2. gloss         — one short gloss line, English preferred, else the Japanese
     gloss verbatim with `lang="ja"`; only the source's own first line;
  3. structure     — the formation pattern's first line, `lang="ja"`.

closed `<details>`, in order
  1. `Examples (N)`                             — every example, per-source label
  2. `Explanation — <source label>`             — one per contributing source
  3. `Also written`                             — other lookup forms, `?query=`
  4. `AI-generated fields (not dictionary fact)` — only when a source flags any
  5. `Sources`                                  — per-source provenance

Missing data omits its row. Nothing is invented, translated, or concatenated
across sources.
"""

from __future__ import annotations

import re
from typing import Any

from bugd.richtext import collapse, first_line, flatten, text_to_content

CARD_ROOT_KEY = "grammarCard"

_LATIN = re.compile(r"[A-Za-z]")
_JLPT_ORDER = ("N5", "N4", "N3", "N2", "N1")


def _role(name: str, tag: str, content: Any, **extra: Any) -> dict:
    node: dict[str, Any] = {"tag": tag, "data": {name: "1"}}
    if content is not None:
        node["content"] = content
    node.update(extra)
    return node


def _looks_english(text: str) -> bool:
    return bool(text) and len(_LATIN.findall(text)) >= max(3, len(text) * 0.3)


def _source_order(entry: dict) -> list[str]:
    order: dict[str, None] = {}
    for point in entry["contributions"]:
        order.setdefault(point["source"], None)
    return list(order)


def _label(source: str, source_labels: dict[str, str]) -> str:
    return source_labels.get(source, source)


def _headword_row(entry: dict) -> dict:
    parts: list[Any] = [
        _role("cardExpression", "span", entry["expression"], lang="ja"),
    ]
    readings = {
        collapse(point["reading"] or "")
        for point in entry["contributions"]
        if collapse(point["reading"] or "") not in ("", entry["expression"])
    }
    if readings:
        parts.append(_role("cardReading", "span", min(readings), lang="ja"))
    levels = [
        level
        for level in _JLPT_ORDER
        if any(point.get("jlpt") == level for point in entry["contributions"])
    ]
    for level in levels:
        parts.append(_role("cardJlpt", "span", level))
    return _role("cardHeadword", "div", parts)


def _gloss_row(entry: dict) -> dict | None:
    japanese: str | None = None
    for point in entry["contributions"]:
        line = first_line(point.get("meaning"))
        if not line:
            continue
        if _looks_english(line):
            return _role("cardGloss", "div", line)
        if japanese is None:
            japanese = line
    if japanese is None:
        return None
    return _role("cardGloss", "div", japanese, lang="ja")


def _structure_row(entry: dict) -> dict | None:
    for point in entry["contributions"]:
        line = first_line(point.get("structure"))
        if line:
            return _role("cardStructure", "div", line, lang="ja")
    return None


def _example_node(example: dict) -> list[Any]:
    japanese = example["japanese"]
    highlights = [h for h in example.get("highlight") or () if h and h in japanese]
    if highlights:
        pattern = "(" + "|".join(re.escape(h) for h in sorted(highlights, key=len, reverse=True)) + ")"
        pieces: list[Any] = []
        for chunk in re.split(pattern, japanese):
            if not chunk:
                continue
            if chunk in highlights:
                pieces.append(
                    _role("cardHighlight", "span", chunk, style={"fontWeight": "bold"})
                )
            else:
                converted = text_to_content(chunk)
                if converted is not None:
                    pieces.append(converted)
        body: Any = pieces
    else:
        converted = text_to_content(japanese)
        body = converted if converted is not None else japanese

    nodes: list[Any] = [_role("cardExampleJa", "div", body, lang="ja")]
    english = collapse(flatten(text_to_content(example.get("english"))))
    if english:
        nodes.append(_role("cardExampleEn", "div", english))
    return nodes


def _examples_section(entry: dict, source_labels: dict[str, str]) -> dict | None:
    groups: list[tuple[str, list[Any]]] = []
    total = 0
    for source in _source_order(entry):
        rendered: list[Any] = []
        seen: set[str] = set()
        for point in entry["contributions"]:
            if point["source"] != source:
                continue
            for example in point.get("examples") or ():
                key = example["japanese"]
                if key in seen:
                    continue  # learner-visible duplicate within one source
                seen.add(key)
                rendered.append(_role("cardExample", "li", _example_node(example)))
        if rendered:
            total += len(rendered)
            groups.append((source, rendered))
    if not groups:
        return None

    content: list[Any] = [
        _role("cardSummary", "summary", f"Examples ({total})"),
    ]
    for source, rendered in groups:
        content.append(
            _role(
                "cardExampleGroup",
                "div",
                [
                    _role("cardSourceLabel", "div", _label(source, source_labels), lang="ja"),
                    _role("cardExampleList", "ul", rendered),
                ],
            )
        )
    return _role("cardExamples", "details", content)


def _explanation_sections(entry: dict, source_labels: dict[str, str]) -> list[dict]:
    sections: list[dict] = []
    for source in _source_order(entry):
        body: list[Any] = []
        for point in entry["contributions"]:
            if point["source"] != source:
                continue
            for field in ("meaning", "structure", "nuance", "explanation", "notes"):
                converted = text_to_content(point.get(field))
                if converted is None:
                    continue
                body.append(
                    _role(
                        "cardField",
                        "div",
                        [
                            _role("cardFieldName", "div", field.capitalize()),
                            _role("cardFieldValue", "div", converted, lang="ja"),
                        ],
                    )
                )
        if not body:
            continue
        sections.append(
            _role(
                "cardExplanation",
                "details",
                [
                    _role(
                        "cardSummary",
                        "summary",
                        f"Explanation — {_label(source, source_labels)}",
                    ),
                    _role("cardExplanationBody", "div", body),
                ],
            )
        )
    return sections


def _also_written_section(entry: dict) -> dict | None:
    variants = [v for v in entry.get("variants") or () if v != entry["expression"]]
    if not variants:
        return None
    items = [
        _role(
            "cardVariant",
            "li",
            {"tag": "a", "href": f"?query={variant}&wildcards=off", "content": variant, "lang": "ja"},
        )
        for variant in variants
    ]
    return _role(
        "cardAlsoWritten",
        "details",
        [
            _role("cardSummary", "summary", "Also written"),
            _role("cardVariantList", "ul", items),
        ],
    )


def _ai_section(entry: dict, source_labels: dict[str, str]) -> dict | None:
    rows: list[Any] = []
    for point in entry["contributions"]:
        flagged = point.get("ai_generated") or {}
        for field, value in sorted(flagged.items()):
            converted = text_to_content(value if isinstance(value, str) else str(value))
            if converted is None:
                continue
            rows.append(
                _role(
                    "cardAiField",
                    "li",
                    [
                        _role(
                            "cardFieldName",
                            "div",
                            f"{_label(point['source'], source_labels)} · {field}",
                        ),
                        _role("cardFieldValue", "div", converted),
                    ],
                )
            )
    if not rows:
        return None
    return _role(
        "cardAiGenerated",
        "details",
        [
            _role(
                "cardSummary",
                "summary",
                "AI-generated fields (not dictionary fact)",
            ),
            _role("cardAiList", "ul", rows),
        ],
    )


def _sources_section(entry: dict, source_labels: dict[str, str]) -> dict:
    rows: list[Any] = []
    for source in _source_order(entry):
        provenance: dict[str, Any] = {}
        for point in entry["contributions"]:
            if point["source"] == source:
                provenance.update(point.get("provenance") or {})
        facts: list[Any] = [
            _role("cardSourceLabel", "div", _label(source, source_labels), lang="ja")
        ]
        band = provenance.get("producerBand") or provenance.get("volume")
        if band:
            facts.append(_role("cardSourceFact", "div", str(band), lang="ja"))
        links = provenance.get("producerLinks") or []
        for link in links:
            if isinstance(link, str) and link.startswith("https://"):
                facts.append(
                    _role(
                        "cardSourceLink",
                        "div",
                        {"tag": "a", "href": link, "content": link},
                    )
                )
        rows.append(_role("cardSource", "li", facts))
    return _role(
        "cardSources",
        "details",
        [
            _role("cardSummary", "summary", "Sources"),
            _role("cardSourceList", "ul", rows),
        ],
    )


def build_card(entry: dict, source_labels: dict[str, str]) -> dict:
    """The whole card as ONE structured-content value."""
    above: list[Any] = [_headword_row(entry)]
    for row in (_gloss_row(entry), _structure_row(entry)):
        if row is not None:
            above.append(row)

    content: list[Any] = [_role("cardAboveFold", "div", above)]
    for section in (
        _examples_section(entry, source_labels),
        *_explanation_sections(entry, source_labels),
        _also_written_section(entry),
        _ai_section(entry, source_labels),
        _sources_section(entry, source_labels),
    ):
        if section is not None:
            content.append(section)

    return {"tag": "div", "data": {CARD_ROOT_KEY: "root"}, "content": content}


__all__ = ["CARD_ROOT_KEY", "build_card"]
