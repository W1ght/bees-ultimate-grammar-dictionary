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

from . import DICTIONARY_AUTHOR, DICTIONARY_FORMAT, DICTIONARY_TITLE, TERM_BANK_SHARD
from .jsonio import MalformedPayload
from .merge import MergedEntry

#: Marker attributes for this dictionary's own CSS. Yomitan preserves
#: `data-sc-*` on structured-content wrappers, so styling targets these rather
#: than Yomitan's generated internals.
CARD_ROOT_ROLE = "grammar-card"


def build_index(revision: str, *, is_updatable: bool = False) -> dict:
    """Build `index.json` for the unified dictionary."""
    if not isinstance(revision, str) or not revision.strip():
        raise MalformedPayload("index revision must be a non-empty string")
    index = {
        "title": DICTIONARY_TITLE,
        "revision": revision,
        "format": DICTIONARY_FORMAT,
        "author": DICTIONARY_AUTHOR,
        "description": (
            "One unified Japanese grammar dictionary combining multiple grammar "
            "sources with per-source attribution."
        ),
        "sourceLanguage": "ja",
        "targetLanguage": "en",
        "sequenced": True,
        "isUpdatable": is_updatable,
    }
    return index


def build_term_entry(entry: MergedEntry, sequence: int) -> list:
    """Build one Yomitan v3 term-bank entry for a merged grammar point.

    Term-bank entry shape (Yomitan v3, positional):
        [expression, reading, definitionTags, deinflectors, score,
         [glossary...], sequence, termTags]

    The glossary carries exactly one structured-content object so the whole card
    is one canonical surface. Card composition is filled in by the card card.
    """
    if not isinstance(entry, MergedEntry):
        raise MalformedPayload("build_term_entry accepts MergedEntry records only")
    raise NotImplementedError("structured-content card composition is not implemented yet")


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
