"""Yomitan structured-content bank generation.

This is the ONLY stage that knows about Yomitan's dictionary format. It turns
`MergedEntry` records into `term_bank_N.json` entries, `tag_bank_1.json`, and
`index.json`.

Card contract (frozen by the card-design card, enforced by tests):

* one canonical surface — a single structured term entry per grammar point;
* compact above the fold: expression, meaning, structure, JLPT;
* progressive disclosure — complete example sentences, per-source explanations,
  nuance, notes, and provenance live in native closed `details` sections;
* per-source attribution visible on every contributed section;
* AI-generated source fields, if rendered at all, only inside an explicitly
  labelled disclosure — never above the fold and never as unlabelled fact.

Nothing here may invent content: no generated meanings, mnemonics, etymology, or
machine translation.
"""

from __future__ import annotations

from . import (
    DICTIONARY_AUTHOR,
    DICTIONARY_FORMAT,
    DICTIONARY_TITLE,
    DICTIONARY_URL,
    TERM_BANK_SHARD,
)
from .jsonio import MalformedPayload
from .merge import MergedEntry
from .model import GrammarPoint
from .richtext import html_to_content, html_to_text

#: Marker attributes for this dictionary's own CSS.
#:
#: `StructuredContentGenerator._setElementDataset` capitalizes the first
#: character of every `data` key and prefixes `sc`, so a key of `grammarCard`
#: becomes `element.dataset.scGrammarCard`, i.e. the DOM attribute
#: `data-sc-grammar-card`. A key of `sc` would instead render as `data-sc-sc`,
#: which is why role names are spelled as the camelCase key here and matched as
#: the hyphenated attribute in `bugd.styles`.
CARD_ROOT_ROLE = "grammarCard"

#: Compact-card budget. Above the fold the card shows the single best meaning and
#: construction; the complete per-source substance lives in disclosures. These
#: bounds are a rendering decision only — nothing is dropped from the archive.
#:
#: `meaning` is a headline, not an essay. DoJG ships senses joined by `;` (up to
#: 375 chars, occasionally with an `---` separator and inlined examples), which
#: would push the disclosures off the first screen of the popup. The compact line
#: keeps whole `;`-delimited senses up to this budget and the complete meaning
#: stays visible in that source's own disclosure.
COMPACT_MEANING_BUDGET = 88

#: A compact construction badge is only useful when it reads as one formula.
#: DoJG's `structure` field is a full markdown-ish table (median 251 chars, max
#: 2284, pipes and row breaks) describing several patterns at once; rendering it
#: in a one-line badge produced `あえて | Verb | | | あえて反対する | ...`. Sources whose
#: structure does not fit a single formula are shown as a table-free
#: construction disclosure instead of a mangled badge.
COMPACT_STRUCTURE_BUDGET = 48

#: Example sentences rendered inside the (closed) Examples disclosure per source.
#: The tail is preserved: sources contribute up to 24 sentences for one point and
#: a scrolling popup is worse than a bounded, readable list.
EXAMPLES_PER_SOURCE = 6

#: One disclosure per contributing SOURCE, not per source record. Real corpora
#: contribute many records to one lookup form (`ない` has 25), and 25 stacked
#: summaries with repeated identical labels is not a readable card.
SENSES_PER_SOURCE = 4


#: Code-point ranges that make a string Japanese for language-tagging purposes:
#: Hiragana, Katakana, CJK punctuation/iteration marks, halfwidth kana, and the
#: CJK Unified Ideographs blocks (including the extensions this corpus can carry).
_JAPANESE_RANGES = (
    (0x3000, 0x303F),  # CJK symbols and punctuation (〜 、 。 〔 〕 ・)
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana phonetic extensions
    (0xFF00, 0xFFEF),  # Halfwidth/fullwidth forms (Ａ Ｎ Ｖ ＋ ＝)
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x20000, 0x3FFFF),  # Supplementary ideographic plane (extensions B..)
)


def _is_japanese_text(text: str) -> bool:
    """True when a string contains Japanese script.

    Source `meaning` fields are NOT uniformly English: DoJG and どんなとき publish
    English glosses, while 絵でわかる日本語, 日本語NET, and 毎日のんびり日本語教師 publish
    Japanese ones (2963 of 4181 non-empty meanings contain Japanese). Hard-coding
    `lang="en"` on the compact line would mis-declare the majority of cards to
    screen readers and give the browser the wrong font and line-breaking rules,
    so the tag is derived from the text itself.
    """
    for character in text:
        codepoint = ord(character)
        for low, high in _JAPANESE_RANGES:
            if low <= codepoint <= high:
                return True
    return False


def _lang_of(text: str) -> str:
    """The BCP-47 tag to declare for a source string."""
    return "ja" if _is_japanese_text(text) else "en"


def _text(value: object) -> str:
    """Collapse a source scalar to a single-line string, or '' when absent."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return html_to_text(value)


def _prose(value: object) -> object | None:
    """Convert a source prose field to structured content, or None when empty."""
    if not isinstance(value, str) or not value.strip():
        return None
    return html_to_content(value)


def _span(role: str, content: object, *, lang: str | None = None) -> dict:
    node: dict = {"tag": "span", "data": {role: ""}, "content": content}
    if lang is not None:
        node["lang"] = lang
    return node


def _highlight_sentence(sentence: str, highlights: tuple[str, ...] | list[str]) -> object:
    """Render a Japanese example, marking the grammar point where the source did.

    Only substrings the SOURCE marked are highlighted — nothing is inferred. The
    longest marker is applied first so a source shipping both `があっての` and
    `あっての` highlights the larger span rather than nesting the smaller one.
    """
    text = sentence
    if not text:
        return ""
    markers = sorted({h for h in (highlights or ()) if isinstance(h, str) and h.strip()}, key=len, reverse=True)
    if not markers:
        return text

    # Split on the source's markers, keeping them, without regex escaping games.
    parts: list[object] = [text]
    for marker in markers:
        nxt: list[object] = []
        for part in parts:
            if not isinstance(part, str):
                nxt.append(part)
                continue
            pieces = part.split(marker)
            for position, piece in enumerate(pieces):
                if position:
                    nxt.append(_span("hl", marker))
                if piece:
                    nxt.append(piece)
        parts = nxt
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0]
    return parts


def _headline(meaning: str) -> str:
    """Shorten a source meaning to a compact headline on a sense boundary.

    Sources join senses with `;` and DoJG sometimes appends an `---` rule plus
    inlined examples. Cutting mid-word would misrepresent the source, so this
    keeps whole `;`-delimited senses while they fit the budget and marks an
    elision with an ellipsis. The complete meaning is always still rendered in
    that source's own disclosure, so nothing is lost.
    """
    text = meaning.split("---")[0].strip(" ;\u3000")
    if len(text) <= COMPACT_MEANING_BUDGET:
        return text
    senses = [s.strip() for s in text.split(";") if s.strip()]
    kept: list[str] = []
    for sense in senses:
        candidate = "; ".join([*kept, sense])
        if kept and len(candidate) > COMPACT_MEANING_BUDGET:
            break
        kept.append(sense)
    headline = "; ".join(kept)
    if len(headline) > COMPACT_MEANING_BUDGET:
        # A single sense longer than the whole budget: cut on a word boundary.
        headline = headline[:COMPACT_MEANING_BUDGET].rsplit(" ", 1)[0]
    return f"{headline}…" if headline != text else headline


def _is_badge_structure(structure: str) -> bool:
    """True when a construction reads as ONE formula fit for a compact badge.

    A source's `structure` is only badge-worthy when it is short and free of
    table punctuation. DoJG's multi-pattern tables fail both tests and are shown
    as a Construction disclosure instead.
    """
    if not structure or len(structure) > COMPACT_STRUCTURE_BUDGET:
        return False
    return "|" not in structure


def _construction_section(point: GrammarPoint) -> dict | None:
    """A source's full construction table, rendered as real structured content.

    Used for sources (DoJG) whose `structure` describes several patterns in a
    pipe-delimited table. Rows become list items so the popup shows the source's
    own patterns instead of a wall of `|` characters.
    """
    structure = _text(point.structure)
    if not structure or _is_badge_structure(structure):
        return None
    raw = point.structure if isinstance(point.structure, str) else ""
    rows: list[dict] = []
    for line in raw.splitlines():
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        rows.append({"tag": "li", "data": {"pattern": ""}, "content": " · ".join(cells)})
    if not rows:
        return None
    return {"tag": "ul", "data": {"patterns": ""}, "content": rows}


def _examples_section(point: GrammarPoint) -> dict | None:
    """A closed `details` block of this source's example sentences."""
    items: list[dict] = []
    for example in point.examples[:EXAMPLES_PER_SOURCE]:
        japanese = example.japanese
        if not isinstance(japanese, str) or not japanese.strip():
            continue
        body: list[object] = [
            {
                "tag": "span",
                "data": {"ja": ""},
                "lang": "ja",
                "content": _highlight_sentence(japanese, example.highlight),
            }
        ]
        english = _text(example.english)
        if english:
            body.append(_span("en", english, lang="en"))
        items.append({"tag": "li", "data": {"example": ""}, "content": body})
    if not items:
        return None
    return {"tag": "ul", "data": {"examples": ""}, "content": items}


def _source_label(point: GrammarPoint) -> str:
    """The human-facing name of the source that contributed a statement."""
    label = point.provenance.get("sourceLabel") if isinstance(point.provenance, dict) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return point.source


def _source_block(point: GrammarPoint) -> list[object]:
    """One contributing source's substance, as renderable nodes.

    Every statement stays attached to the source that made it: explanation,
    nuance, and notes are never merged across sources or averaged. Returns an
    empty list when this record has nothing to show.
    """
    body: list[object] = []
    for field_name in ("explanation", "nuance", "notes"):
        raw = getattr(point, field_name, None)
        content = _prose(raw)
        if content is not None:
            # Prose is Japanese for most sources but English for DoJG (373 of its
            # explanations); the card root declares `ja`, so an English block must
            # say so explicitly or it inherits the wrong language.
            node: dict = {"tag": "div", "data": {"prose": ""}, "content": content}
            if isinstance(raw, str):
                node["lang"] = _lang_of(raw)
            body.append(node)
    construction = _construction_section(point)
    if construction is not None:
        body.append(construction)
    examples = _examples_section(point)
    if examples is not None:
        body.append(examples)
    if not body:
        return []
    return body


def _sense_label(point: GrammarPoint, ordinal: int, total: int) -> str:
    """A distinguishing label for one of several senses from the same source.

    Sources contribute several records to one lookup form (`ない` has 20 records
    from one source). Repeating the identical source name on each disclosure is
    unreadable, so a sense that carries its own meaning is labelled with it and
    the rest are numbered.
    """
    if total <= 1:
        return ""
    meaning = _text(point.meaning)
    if meaning:
        return _headline(meaning)
    structure = _text(point.structure)
    if structure and _is_badge_structure(structure):
        return structure
    return f"Sense {ordinal}"


def _source_blocks(entry: MergedEntry) -> list[dict]:
    """One disclosure per contributing SOURCE, senses nested inside it.

    Grouping by source (rather than by source record) is what keeps a card
    readable: `ない` contributes 25 records across 5 sources, which previously
    produced 25 sibling disclosures with repeated identical summary labels. Now
    each source is one disclosure whose summary names the source once, and its
    individual senses are labelled subsections inside it.
    """
    grouped: dict[str, list[GrammarPoint]] = {}
    for point in entry.contributions:
        grouped.setdefault(_source_label(point), []).append(point)

    blocks: list[dict] = []
    for label, points in grouped.items():
        rendered: list[tuple[GrammarPoint, list[object]]] = []
        for point in points:
            body = _source_block(point)
            if body:
                rendered.append((point, body))
        if not rendered:
            continue

        shown = rendered[:SENSES_PER_SOURCE]
        body: list[object] = []
        for ordinal, (point, sense_body) in enumerate(shown, start=1):
            sense_label = _sense_label(point, ordinal, len(shown))
            if sense_label:
                body.append(
                    {
                        "tag": "div",
                        "data": {"senseLabel": ""},
                        "lang": _lang_of(sense_label),
                        "content": sense_label,
                    }
                )
            body.append({"tag": "div", "data": {"sense": ""}, "content": sense_body})

        blocks.append(
            {
                "tag": "details",
                "data": {"sourceBlock": ""},
                "content": [
                    {
                        "tag": "summary",
                        "content": [_span("sourceName", label)],
                    },
                    {"tag": "div", "content": body},
                ],
            }
        )
    return blocks


def _alias_target(point: GrammarPoint) -> str:
    """The canonical form an alias-only source record points at.

    Sources ship spelling-variant stubs (`相まって` -> `あいまって`, `後` -> `あと`)
    that carry no meaning, structure, prose, or examples of their own. Rendering
    one as a card whose only content is a `Sources` disclosure is a dead end for
    the reader, so the card instead points at the form that holds the substance.

    Some `alias-redirect` records set `aliasOf` to the headword itself and carry
    the real target only as an internal `?query=` producer link (`あって` ->
    `?query=にあって`), so an internal producer link is consulted as well. Only
    internal `?query=` links are trusted here: an external URL is provenance, not
    a dictionary cross-reference.
    """
    provenance = point.provenance if isinstance(point.provenance, dict) else {}
    for key in ("aliasOf", "canonicalExpression", "seeAlso"):
        value = provenance.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != point.expression:
            return value.strip()

    links = provenance.get("producerLinks")
    if isinstance(links, (list, tuple)):
        for link in links:
            if not isinstance(link, str) or not link.startswith("?query="):
                continue
            target = link[len("?query=") :].split("&", 1)[0].strip()
            if target and target != point.expression:
                return target
    return ""


def _producer_page(point: GrammarPoint) -> str:
    """The source's own external page for this grammar point, if it published one."""
    provenance = point.provenance if isinstance(point.provenance, dict) else {}
    links = provenance.get("producerLinks")
    if isinstance(links, (list, tuple)):
        for link in links:
            if isinstance(link, str) and link.startswith(("http://", "https://")):
                return link
    return ""


def _headword_only_block(entry: MergedEntry) -> dict | None:
    """Honest handling of a record the source listed but never described.

    Some sources index a grammar point in a running list without shipping a
    meaning, structure, prose, or examples for it. Inventing a gloss would be
    fabricated dictionary content, and a card whose only content is a `Sources`
    disclosure reads as broken. Instead the card states plainly that the source
    lists the form without an explanation, and links the source's own page when
    one exists so the reader can go there.
    """
    for point in entry.contributions:
        page = _producer_page(point)
        if not page:
            continue
        return {
            "tag": "div",
            "data": {"listedOnly": ""},
            "lang": "en",
            "content": [
                f"Listed by {_source_label(point)} without an explanation — ",
                {"tag": "a", "href": page, "content": "see the source page"},
                ".",
            ],
        }
    # No redirect and no published page: 3 of 2,419 real corpus entries reach
    # here. Naming the source is still strictly more honest and more useful than
    # a card whose entire visible content is a `Sources` disclosure, so the same
    # statement is made without a link rather than left blank.
    names: list[str] = []
    for point in entry.contributions:
        label = _source_label(point)
        if label not in names:
            names.append(label)
    if not names:
        return None
    return {
        "tag": "div",
        "data": {"listedOnly": ""},
        "lang": "en",
        "content": f"Listed by {', '.join(names)} without an explanation.",
    }


def _crossreference_block(entry: MergedEntry) -> dict | None:
    """A visible 'see <form>' pointer for an entry with no substance of its own.

    Only emitted when the entry genuinely has nothing to show and a source names
    a canonical form. The target is a clickable internal Yomitan lookup, so the
    reader reaches the real card in one tap instead of hitting an empty card.
    """
    targets: list[str] = []
    for point in entry.contributions:
        target = _alias_target(point)
        if target and target != entry.expression and target not in targets:
            targets.append(target)
    if not targets:
        return None

    body: list[object] = ["see "]
    for position, target in enumerate(targets):
        if position:
            body.append(", ")
        body.append(
            {
                "tag": "a",
                "href": f"?query={target}&wildcards=off",
                "lang": "ja",
                "content": target,
            }
        )
    return {"tag": "div", "data": {"crossref": ""}, "content": body}


def _compact_block(entry: MergedEntry) -> dict:
    """Above-the-fold block: meaning, then a quiet construction/JLPT row.

    Selection is deterministic: the first contribution (merge order) that
    supplies each field wins, and conflicting values are NOT averaged or
    silently picked — they remain visible per source in the disclosures below.
    The headword itself is not repeated; Yomitan renders it with furigana
    immediately above this block.
    """
    meaning = ""
    structure = ""
    jlpt = ""
    for point in entry.contributions:
        if not meaning:
            candidate = _text(point.meaning)
            if candidate:
                meaning = _headline(candidate)
        if not structure:
            candidate = _text(point.structure)
            # Only a single readable formula earns a compact badge; multi-pattern
            # tables are rendered in that source's Construction list instead.
            if _is_badge_structure(candidate):
                structure = candidate
        if not jlpt and point.jlpt:
            jlpt = point.jlpt

    body: list[object] = []
    if meaning:
        # Sources publish meanings in English OR Japanese; declare what this one
        # actually is rather than assuming English.
        body.append(_span("meaning", meaning, lang=_lang_of(meaning)))

    metarow: list[object] = []
    if structure:
        metarow.append(_span("structure", structure, lang="ja"))
    if jlpt:
        metarow.append(_span("jlpt", jlpt))
    if metarow:
        body.append({"tag": "div", "data": {"metarow": ""}, "content": metarow})

    return {"tag": "div", "data": {"compact": ""}, "content": body}


def _attribution_block(entry: MergedEntry) -> dict:
    """Closed disclosure naming every source that contributed to this entry."""
    names: list[str] = []
    for point in entry.contributions:
        label = _source_label(point)
        if label not in names:
            names.append(label)
    return {
        "tag": "details",
        "content": [
            {"tag": "summary", "content": "Sources"},
            {
                "tag": "div",
                "content": [
                    {
                        "tag": "div",
                        "data": {"attribution": ""},
                        "content": f"Contributed by {', '.join(names)}.",
                    }
                ],
            },
        ],
    }


def build_term_entry(entry: MergedEntry, sequence: int) -> list:
    """Build one Yomitan v3 term-bank entry for a merged grammar point.

    Term-bank entry shape (Yomitan v3, positional):
        [expression, reading, definitionTags, deinflectors, score,
         [glossary...], sequence, termTags]

    The glossary carries exactly one structured-content object so the whole card
    is one canonical surface: compact meaning/construction/JLPT above the fold,
    then native closed `details` disclosures per contributing source, then a
    closed attribution disclosure.
    """
    if not isinstance(entry, MergedEntry):
        raise MalformedPayload("build_term_entry accepts MergedEntry records only")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise MalformedPayload("term-entry sequence must be a positive integer")

    content: list[object] = [_compact_block(entry)]
    source_blocks = _source_blocks(entry)
    if not source_blocks:
        # Nothing but attribution would render. Two honest fallbacks, in order:
        # an alias-only spelling variant points at the form carrying the
        # substance; a listed-but-undescribed headword says so and links the
        # source's own page. Neither invents dictionary content.
        fallback = _crossreference_block(entry) or _headword_only_block(entry)
        if fallback is not None:
            content.append(fallback)
    content.extend(source_blocks)
    content.append(_attribution_block(entry))

    reading = ""
    for point in entry.contributions:
        candidate = point.reading or ""
        # Yomitan treats reading == expression as a redundant furigana pair.
        if candidate and candidate != entry.expression:
            reading = candidate
            break

    return [
        entry.expression,
        reading,
        "",
        "",
        0,
        [
            {
                "type": "structured-content",
                "content": {
                    "tag": "div",
                    "data": {CARD_ROOT_ROLE: ""},
                    "lang": "ja",
                    "content": content,
                },
            }
        ],
        sequence,
        "",
    ]


def build_index(
    revision: str,
    *,
    index_url: str | None = None,
    download_url: str | None = None,
    source_labels: dict[str, str] | None = None,
) -> dict:
    """Build `index.json` for the unified dictionary.

    Yomitan's index schema pins `isUpdatable` to `const: true` and makes it
    depend on both `indexUrl` and `downloadUrl`, so a self-updating index is
    valid only as all three together. The dictionary is local-only by default:
    the updater fields are omitted unless both URLs are supplied.

    `attribution` names every contributing source by its human-facing label, so
    the licence notices required by the per-source terms travel with the archive
    and are visible in Yomitan's dictionary details pane rather than only inside
    individual cards.
    """
    if not isinstance(revision, str) or not revision.strip():
        raise MalformedPayload("index revision must be a non-empty string")
    index = {
        "title": DICTIONARY_TITLE,
        "revision": revision,
        "format": DICTIONARY_FORMAT,
        "author": DICTIONARY_AUTHOR,
        "url": DICTIONARY_URL,
        "description": (
            "One unified Japanese grammar dictionary combining multiple grammar "
            "sources with per-source attribution."
        ),
        "sourceLanguage": "ja",
        "targetLanguage": "en",
        "sequenced": True,
    }
    labels = sorted({label for label in (source_labels or {}).values() if label})
    if labels:
        index["attribution"] = (
            "Grammar content contributed by: " + "; ".join(labels) + "."
        )
    if (index_url is None) != (download_url is None):
        raise MalformedPayload("a self-updating index requires both indexUrl and downloadUrl")
    if index_url is not None and download_url is not None:
        index["indexUrl"] = index_url
        index["downloadUrl"] = download_url
        index["isUpdatable"] = True
    return index


def build_banks(entries: list[MergedEntry]) -> dict[str, list]:
    """Shard merged entries into named Yomitan bank members.

    Returns a mapping of ZIP member name -> bank payload. Sharding is bounded at
    `TERM_BANK_SHARD` ordered entries per bank so constrained imports can advance
    bank by bank. An empty corpus yields no bank members: a scaffold build is
    honest about having no entries rather than shipping a placeholder record.
    """
    for entry in entries:
        if not isinstance(entry, MergedEntry):
            raise MalformedPayload("build_banks accepts MergedEntry records only")

    banks: dict[str, list] = {}
    for offset in range(0, len(entries), TERM_BANK_SHARD):
        shard = entries[offset : offset + TERM_BANK_SHARD]
        number = offset // TERM_BANK_SHARD + 1
        banks[f"term_bank_{number}.json"] = [
            build_term_entry(entry, offset + position + 1)
            for position, entry in enumerate(shard)
        ]
    return banks


def build_tag_bank(source_labels: dict[str, str]) -> list:
    """Build `tag_bank_1.json` from per-source attribution labels.

    Tag-bank entry shape (Yomitan v3, positional):
        [name, category, order, notes, score]
    """
    bank = []
    for order, name in enumerate(sorted(source_labels)):
        bank.append([name, "source", order, source_labels[name], 0])
    return bank


__all__ = [
    "CARD_ROOT_ROLE",
    "build_index",
    "build_term_entry",
    "build_banks",
    "build_tag_bank",
]
