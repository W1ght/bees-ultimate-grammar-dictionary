"""Card CSS shipped as the dictionary's `styles.css`.

Yomitan does not apply this file verbatim. `Display._getCustomCss` wraps the
whole stylesheet in one nesting block:

    [data-dictionary="Bee's Ultimate Grammar Dictionary"] { <this file> }

Two consequences drive every rule below.

1. Every selector is resolved as a DESCENDANT of the dictionary scope, so a
   top-level `:root` or `@media (prefers-color-scheme: ...)` block declaring
   design tokens can never match the card. Tokens are declared on the card
   wrapper itself.
2. Dark mode is Yomitan's own `:root[data-theme=dark]`, driven by the user's
   Yomitan appearance setting — NOT the OS-level `prefers-color-scheme`. Because
   the scope wrapper sits below `:root`, this file cannot match that attribute
   either. Instead of re-deriving a palette, the card inherits Yomitan's own
   theme variables (`--text-color`, `--text-color-light2/3`, `--light-border-color`,
   `--tag-*`), which the host already re-declares per theme. That makes light,
   dark, and any future theme correct by construction.

`data` keys become dataset properties through
`StructuredContentGenerator._setElementDataset`, which capitalizes the first
character and prefixes `sc`. So `data:{grammarCard:'...'}` is the only way to
get a `data-sc-grammar-card` attribute; a key of `sc` would render as
`data-sc-sc`. Selectors here match the keys `bugd.banks` actually emits.
"""

from __future__ import annotations

STYLES_CSS = """\
/* Yomitan wraps this file in [data-dictionary="..."] { ... }, so every rule
   below is scoped to this dictionary's own entries and cannot restyle Yomitan
   or another dictionary. Colours come from Yomitan's theme variables so light
   and dark themes are inherited rather than re-implemented. */

[data-sc-grammar-card] {
  --bugd-row-gap: 0.5em;
  --bugd-inline-gap: 0.5em;
  --bugd-rule: var(--light-border-color, #eee);
  --bugd-muted: var(--text-color-light2, #666);
  --bugd-quiet: var(--text-color-light3, #777);
  --bugd-radius: 0.3em;

  display: flow-root;
  line-height: 1.65;
  /* Yomitan never declares a containment context, so the card declares its own.
     Narrow-popup rules below then respond to the CARD's width rather than to the
     viewport, which is what actually matters: the same card is rendered in a
     ~320px popup, in a wide search page, and inside Anki previews. */
  container-type: inline-size;
  container-name: bugd-card;
}

/* ---------------------------------------------------------------- compact */
/* Above the fold: meaning first at full readable size, then a quiet metadata
   row. The expression itself is NOT repeated here — Yomitan already renders the
   headword with furigana directly above, so repeating it wastes the first line
   of the popup. */

[data-sc-compact] {
  display: flow-root;
}

[data-sc-meaning] {
  display: block;
  /* Yomitan's base font is 14px and it renders the headword at the SAME 14px in
     the search page, so a 1.05em meaning reads as undifferentiated body text.
     1.15em plus weight 650 makes the gloss the clear primary element without
     shouting, and stays proportional if the user changes Yomitan's font size. */
  font-size: 1.15em;
  font-weight: 650;
  line-height: 1.45;
  /* Source meanings can be multi-line; keep the wrapping natural. */
  white-space: pre-line;
}

[data-sc-metarow] {
  display: flex;
  flex-flow: row wrap;
  align-items: baseline;
  gap: 0.3em var(--bugd-inline-gap);
  margin-top: 0.4em;
}

/* Grammatical construction: monospace-ish so ＋ / 〔〕 slots stay aligned,
   and visually distinct from the English meaning. */
[data-sc-structure] {
  font-size: 0.92em;
  color: var(--bugd-muted);
  padding: 0.1em 0.45em;
  border: 1px solid var(--bugd-rule);
  border-radius: var(--bugd-radius);
  /* Long constructions must wrap inside the popup, never overflow it. */
  overflow-wrap: anywhere;
}

/* JLPT level: a compact badge. Yomitan's own tag palette keeps it legible in
   both themes and in forced-colors mode. */
[data-sc-jlpt] {
  flex: none;
  font-size: 0.82em;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--tag-text-color, #fff);
  background: var(--tag-default-background-color, #8a8a91);
  border-radius: 0.9em;
  padding: 0.05em 0.55em;
}

/* --------------------------------------------------------------- details */
/* Progressive disclosure. Summaries are the only interactive affordance on the
   card, so they get a real hit area and a visible focus ring. */

[data-sc-grammar-card] details {
  margin-top: var(--bugd-row-gap);
  border-top: 1px solid var(--bugd-rule);
}

[data-sc-grammar-card] summary {
  /* min-height keeps the touch target usable; 44px is the platform guidance and
     the card is read on phones through Yomitan's Android popup too. */
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.3em 0;
  font-size: 0.9em;
  font-weight: 600;
  color: var(--bugd-muted);
  cursor: pointer;
  /* The native marker is kept: it is the disclosure affordance, it rotates on
     open, and it survives forced-colors mode. */
}

[data-sc-grammar-card] summary:hover {
  color: var(--text-color, inherit);
}

[data-sc-grammar-card] summary:focus-visible {
  outline: 2px solid var(--accent-color, Highlight);
  outline-offset: 2px;
  border-radius: var(--bugd-radius);
}

[data-sc-grammar-card] details > div {
  padding: 0.1em 0 0.5em;
}

/* Cross-reference for a spelling-variant entry that carries no substance of its
   own: the pointer IS the content, so it is legible rather than a quiet footnote. */
[data-sc-crossref] {
  font-size: 0.95em;
  color: var(--bugd-muted);
}

[data-sc-crossref] a {
  color: var(--link-color, var(--accent-color, inherit));
  font-weight: 600;
}

/* A headword the source listed without describing. Stated plainly and quietly —
   no invented gloss, and visibly not a normal definition. */
[data-sc-listed-only] {
  font-size: 0.9em;
  font-style: italic;
  color: var(--bugd-quiet);
}

[data-sc-listed-only] a {
  color: var(--link-color, var(--accent-color, inherit));
  font-style: normal;
  overflow-wrap: anywhere;
}

/* --------------------------------------------------- senses & patterns */
/* A source contributing several senses to one lookup form gets ONE disclosure
   with labelled subsections, rather than several sibling disclosures repeating
   the same source name. */

[data-sc-sense-label] {
  margin-top: 0.5em;
  font-weight: 600;
  font-size: 0.92em;
  color: var(--text-color, inherit);
}

[data-sc-sense] + [data-sc-sense-label] {
  border-top: 1px dashed var(--bugd-rule);
  padding-top: 0.5em;
}

/* Construction patterns: sources whose `structure` is a multi-pattern table are
   rendered as a real list here instead of a mangled one-line badge. */
[data-sc-patterns] {
  list-style: none;
  margin: 0.2em 0 0;
  padding: 0;
}

[data-sc-pattern] {
  margin: 0 0 0.25em;
  font-size: 0.92em;
  color: var(--bugd-muted);
  overflow-wrap: anywhere;
}

/* ------------------------------------------------------------- examples */
/* Example sentences are the most-read disclosure, so they are set at full size
   with generous leading for furigana, and the bullet column is removed in
   favour of a quiet left rule. */

[data-sc-examples] {
  list-style: none;
  margin: 0;
  padding: 0;
}

[data-sc-example] {
  margin: 0 0 0.55em;
  padding-left: 0.7em;
  border-left: 2px solid var(--bugd-rule);
}

[data-sc-example]:last-child {
  margin-bottom: 0;
}

/* Japanese sentence: ruby needs vertical room or the annotation collides with
   the line above. */
[data-sc-ja] {
  display: block;
  line-height: 2;
}

[data-sc-ja] ruby > rt {
  font-size: 0.55em;
  /* Keep furigana visually attached to its base text. */
  line-height: 1.1;
  user-select: none;
}

/* The grammar point in context. Underline rather than colour alone, so the
   highlight survives forced-colors mode and colour-blind reading. */
[data-sc-hl] {
  font-weight: 700;
  text-decoration: underline;
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.18em;
}

/* Translation: clearly subordinate to the Japanese it belongs to. */
[data-sc-en] {
  display: block;
  font-size: 0.9em;
  line-height: 1.5;
  color: var(--bugd-quiet);
}

/* ------------------------------------------------------- prose sections */

[data-sc-prose] {
  white-space: pre-line;
}

[data-sc-prose] div + div {
  margin-top: 0.4em;
}

/* Per-source attribution: quiet, small, and always last. */
[data-sc-attribution] {
  font-size: 0.85em;
  color: var(--bugd-quiet);
}

[data-sc-attribution] a {
  color: var(--link-color, var(--accent-color, inherit));
  overflow-wrap: anywhere;
}

/* Multi-source entries: each contributing source is its own labelled disclosure
   so a statement is never detached from the source that made it. */
[data-sc-source-name] {
  font-weight: 600;
  color: var(--bugd-muted);
}

/* --------------------------------------------------------- narrow popup */
/* Yomitan's popup can be ~320px wide. The metadata row must reflow rather than
   force horizontal scrolling. */

@container bugd-card (max-width: 26em) {
  [data-sc-meaning] {
    /* Slightly smaller in a phone-width popup, but still clearly larger than the
       metadata row beneath it — the hierarchy must survive the narrow layout. */
    font-size: 1.08em;
  }
  [data-sc-metarow] {
    gap: 0.25em 0.4em;
  }
}

/* --------------------------------------------------------- forced colors */
/* Preserve boundaries and the badge shape when the user's OS overrides colour. */

@media (forced-colors: active) {
  [data-sc-grammar-card] {
    --bugd-rule: CanvasText;
    --bugd-muted: CanvasText;
    --bugd-quiet: CanvasText;
  }
  [data-sc-jlpt] {
    color: CanvasText;
    background: transparent;
    border: 1px solid CanvasText;
  }
  [data-sc-structure] {
    border-color: CanvasText;
  }
}

/* ------------------------------------------------------- reduced motion */

@media (prefers-reduced-motion: reduce) {
  [data-sc-grammar-card] * {
    transition: none !important;
    animation: none !important;
  }
}
"""


__all__ = ["STYLES_CSS"]
