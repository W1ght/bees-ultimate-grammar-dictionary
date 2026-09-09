"""Selectors for the card's own roles, as they exist in the rendered DOM.

Yomitan assigns structured-content `data` keys with `element.dataset[key]`, which
prefixes `sc` and upper-cases the first character, so the role `cardGloss`
becomes the attribute `data-sc-card-gloss`. Tests address the card through these
constants so a role rename is one edit and a failure names a real attribute a
human can find in the DOM.
"""

from __future__ import annotations

ROOT = "[data-sc-grammar-card]"

ABOVE_FOLD = "[data-sc-card-above-fold]"
HEADWORD = "[data-sc-card-headword]"
EXPRESSION = "[data-sc-card-expression]"
READING = "[data-sc-card-reading]"
JLPT = "[data-sc-card-jlpt]"
GLOSS = "[data-sc-card-gloss]"
STRUCTURE = "[data-sc-card-structure]"

SUMMARY = "[data-sc-card-summary]"
EXAMPLES = "[data-sc-card-examples]"
EXAMPLE = "[data-sc-card-example]"
EXAMPLE_JA = "[data-sc-card-example-ja]"
EXAMPLE_EN = "[data-sc-card-example-en]"
EXAMPLE_GROUP = "[data-sc-card-example-group]"
HIGHLIGHT = "[data-sc-card-highlight]"
EXPLANATION = "[data-sc-card-explanation]"
FIELD_NAME = "[data-sc-card-field-name]"
FIELD_VALUE = "[data-sc-card-field-value]"
ALSO_WRITTEN = "[data-sc-card-also-written]"
VARIANT = "[data-sc-card-variant]"
AI_GENERATED = "[data-sc-card-ai-generated]"
SOURCES = "[data-sc-card-sources]"
SOURCE = "[data-sc-card-source]"
SOURCE_LABEL = "[data-sc-card-source-label]"
SOURCE_FACT = "[data-sc-card-source-fact]"
SOURCE_LINK = "[data-sc-card-source-link]"

#: The above-fold rows, in the order the card contract freezes them.
ABOVE_FOLD_ROWS = (HEADWORD, GLOSS, STRUCTURE)

#: The disclosure sections, in contract order.
DISCLOSURE_SECTIONS = (
    EXAMPLES,
    EXPLANATION,
    ALSO_WRITTEN,
    AI_GENERATED,
    SOURCES,
)

__all__ = [name for name in dir() if name.isupper()]
