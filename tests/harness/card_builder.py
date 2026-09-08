"""Card builder the geometry/behaviour suite renders.

UGD-12 tests *rendered behaviour*, so it needs a card to render. Resolution order:

1. `bugd.banks.build_term_entry` — the production composer. Used as soon as
   UGD-09 implements it, so this suite becomes a real regression gate on the
   shipped card rather than on a local approximation.
2. `reference_card.build_card` — a contract-faithful stand-in derived from
   `docs/card-contract.md`, used only while (1) still raises
   `NotImplementedError`.

`active_builder()` reports which one is live, and `test_card_source.py` asserts
the switch happens automatically, so the suite can never silently keep testing
the stand-in after the production composer lands.
"""

from __future__ import annotations

from typing import Any, Callable

#: Yomitan assigns `data` keys via `element.dataset[key]` after prefixing `sc`
#: and upper-casing the first character. A `DOMStringMap` setter rejects any
#: name containing `-` followed by an ASCII lowercase letter, and the generator
#: swallows that exception, so a hyphen-case role emits *no attribute at all*.
#: The role must be camelCase for `[data-sc-grammar-card]` to exist in the DOM.
CARD_ROOT_KEY = "grammarCard"

CARD_ROOT_SELECTOR = "[data-sc-grammar-card]"


def _production_builder() -> Callable[[Any, int], list] | None:
    try:
        from bugd.banks import build_term_entry
        from bugd.merge import MergedEntry
    except Exception:
        return None

    probe = MergedEntry(expression="x")
    try:
        build_term_entry(probe, 1)
    except NotImplementedError:
        return None
    except Exception:
        # Any other failure means the composer exists and is doing real work;
        # a bare probe entry simply is not valid input for it.
        pass
    return build_term_entry


def reference_available() -> bool:
    """Whether the contract stand-in can be imported.

    `reference_card` needs `bugd.richtext` (UGD-09's text-conversion module). When
    the production composer has not landed *and* that module is absent, this suite
    has nothing to render: it must skip loudly rather than fail with an import
    error that looks like a broken test file.
    """
    try:
        import bugd.richtext  # noqa: F401
    except Exception:
        return False
    return True


def unavailable_reason() -> str | None:
    """Why no card can be built, or `None` when one can."""
    if _production_builder() is not None:
        return None
    if not reference_available():
        return (
            "no card source available: bugd.banks.build_term_entry still raises "
            "NotImplementedError (UGD-09) and the contract stand-in needs "
            "bugd.richtext, which is not importable"
        )
    return None


def active_builder() -> str:
    """`"production"` once `bugd.banks.build_term_entry` composes cards."""
    return "production" if _production_builder() is not None else "reference"


def build_card(entry: dict, source_labels: dict[str, str], sequence: int = 1) -> Any:
    """Structured-content value for one merged corpus entry (as JSON dict)."""
    builder = _production_builder()
    if builder is None:
        from . import reference_card

        return reference_card.build_card(entry, source_labels)
    return _extract_structured_content(builder(_to_merged_entry(entry), sequence))


def _extract_structured_content(term_entry: list) -> Any:
    glossary = term_entry[5]
    if not isinstance(glossary, list) or len(glossary) != 1:
        raise AssertionError(
            "card contract: glossary must hold exactly ONE structured-content "
            f"object (one canonical surface); got {type(glossary).__name__} "
            f"of length {len(glossary) if isinstance(glossary, list) else 'n/a'}"
        )
    item = glossary[0]
    if not isinstance(item, dict) or item.get("type") != "structured-content":
        raise AssertionError(
            f"card contract: glossary[0] must be structured-content; got {item!r:.120}"
        )
    return item["content"]


def _to_merged_entry(entry: dict) -> Any:
    from bugd.merge import MergedEntry
    from bugd.model import Example, GrammarPoint

    contributions = []
    for raw in entry["contributions"]:
        contributions.append(
            GrammarPoint(
                source=raw["source"],
                source_id=raw["source_id"],
                expression=raw["expression"],
                variants=tuple(raw.get("variants") or ()),
                reading=raw.get("reading"),
                meaning=raw.get("meaning"),
                structure=raw.get("structure"),
                nuance=raw.get("nuance"),
                explanation=raw.get("explanation"),
                notes=raw.get("notes"),
                jlpt=raw.get("jlpt"),
                examples=tuple(
                    Example(
                        japanese=ex["japanese"],
                        english=ex.get("english"),
                        highlight=tuple(ex.get("highlight") or ()),
                        ai_generated=bool(ex.get("ai_generated")),
                    )
                    for ex in raw.get("examples") or ()
                ),
                tags=tuple(raw.get("tags") or ()),
                ai_generated=dict(raw.get("ai_generated") or {}),
                provenance=dict(raw.get("provenance") or {}),
            )
        )
    merged = MergedEntry(
        expression=entry["expression"],
        variants=tuple(entry.get("variants") or ()),
        contributions=contributions,
    )
    return merged


__all__ = ["CARD_ROOT_KEY", "CARD_ROOT_SELECTOR", "active_builder", "build_card"]
