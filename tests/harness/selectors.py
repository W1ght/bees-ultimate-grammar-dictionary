"""Selectors for the card's own roles, as they exist in the rendered DOM.

Yomitan assigns structured-content `data` keys with `element.dataset[key]`, which
prefixes `sc` and upper-cases the first character, so the role `sourceName`
becomes the attribute `data-sc-source-name`. Tests address the card through these
constants so a role rename is one edit and a failure names a real attribute a
human can find in the DOM.

These constants track the PRODUCTION composer (`bugd.banks.build_term_entry`),
which is the card that actually ships. Every value below was confirmed against a
real card dumped from the pinned Yomitan renderer, not assumed from an older
stand-in. The production card's shape:

* the whole card is one ``[data-sc-grammar-card]`` root (Yomitan renders the
  headword with furigana ABOVE it, so the card itself carries no headword row);
* above the fold is one compact block ``[data-sc-compact]`` holding the gloss
  (``[data-sc-meaning]``) and a metadata row (``[data-sc-metarow]``) of the
  construction badge (``[data-sc-structure]``) and JLPT chip (``[data-sc-jlpt]``);
* progressive disclosure is one native ``details`` PER CONTRIBUTING SOURCE
  (``[data-sc-source-block]``), whose ``summary`` names the source
  (``[data-sc-source-name]``) — the source IS the attribution, so there is no
  separate trailing "Sources" section. Inside a source block live its senses,
  per-source JLPT levels, prose explanations, construction patterns, and example
  sentences.
"""

from __future__ import annotations

#: The whole card: one structured-content root per grammar point.
ROOT = "[data-sc-grammar-card]"

#: Above the fold: the compact block. Yomitan renders the headword with furigana
#: directly above the card, so the card's own first surface is this block, which
#: holds the gloss and the quiet construction/JLPT metadata row and nothing else.
ABOVE_FOLD = "[data-sc-compact]"

#: The gloss / meaning line — the card's primary above-the-fold statement. The
#: production card does not repeat the headword (Yomitan already shows it), so the
#: gloss is the headword row's payload.
GLOSS = "[data-sc-meaning]"
MEANING = GLOSS

#: The metadata row beneath the gloss: construction badge + JLPT chip.
METAROW = "[data-sc-metarow]"

#: The construction badge (one readable formula; multi-pattern structures render
#: as a Construction list inside a disclosure instead).
STRUCTURE = "[data-sc-structure]"

#: JLPT level chip. Appears above the fold (first source to claim a level) and,
#: for cross-source disagreements, again inside each source's own disclosure.
JLPT = "[data-sc-jlpt]"

#: The above-fold surface is Japanese-tagged: the compact block sits inside the
#: card root, which carries `lang="ja"`, and the gloss span declares the language
#: of the meaning it renders. Kept as an alias so tests that name a "headword" /
#: "expression" surface address the real above-fold block.
HEADWORD = ABOVE_FOLD
EXPRESSION = GLOSS
READING = "ruby > rt"

#: Progressive disclosure. Each contributing SOURCE is one native `details`
#: whose `summary` names the source. There is no separate Examples/Explanation/
#: Sources section: the substance (prose, patterns, examples) lives inside each
#: source's own block, and the source name IS the attribution.
SOURCE = "[data-sc-source-block]"
SOURCES = SOURCE
SUMMARY = "[data-sc-source-block] > summary"
SOURCE_LABEL = "[data-sc-source-name]"

#: A source's own JLPT claim, stated inside its disclosure (for the entries where
#: sources disagree on the level).
SOURCE_LEVEL = "[data-sc-source-level]"

#: Explanation prose (the per-source explanation / nuance / notes block).
EXPLANATION = "[data-sc-prose]"

#: A labelled sense subsection inside a source block, and its label.
SENSE = "[data-sc-sense]"
SENSE_LABEL = "[data-sc-sense-label]"

#: Construction patterns rendered as a list (multi-pattern structures).
PATTERNS = "[data-sc-patterns]"
PATTERN = "[data-sc-pattern]"

#: Example sentences. The list, one item, and the Japanese / English / highlight
#: spans inside an item.
EXAMPLES = "[data-sc-examples]"
EXAMPLE = "[data-sc-example]"
EXAMPLE_JA = "[data-sc-ja]"
EXAMPLE_EN = "[data-sc-en]"
HIGHLIGHT = "[data-sc-hl]"

#: In-prose example runs (examples a producer wrote inside its explanation field).
EXAMPLE_LABEL = "[data-sc-example-label]"
INLINE_EXAMPLE = "[data-sc-inline-example]"

#: A spelling-variant / alias-only entry whose only content is a "see <form>"
#: cross-reference to the form that carries the substance.
CROSSREF = "[data-sc-crossref]"

#: A headword a source listed without describing.
LISTED_ONLY = "[data-sc-listed-only]"

#: The above-fold rows, in the order the card contract freezes them: the gloss,
#: then the construction/JLPT metadata row. These are the two children the compact
#: block renders (a sparse entry may render neither).
ABOVE_FOLD_ROWS = (GLOSS, METAROW)

#: The dataset keys the compact (above-fold) block is allowed to carry as direct
#: children, as `element.dataset` reports them (camelCase, sans the `data-sc-`
#: attribute prefix). Nothing else may appear above the fold.
ABOVE_FOLD_CHILD_ROLES = frozenset({"scMeaning", "scMetarow"})

#: The disclosure sections, in contract order. The production card discloses one
#: section per contributing source, so the disclosures ARE the source blocks.
DISCLOSURE_SECTIONS = (SOURCE,)

__all__ = [name for name in dir() if name.isupper()] + ["ABOVE_FOLD_CHILD_ROLES"]
