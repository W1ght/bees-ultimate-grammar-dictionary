"""Card CSS shipped as the dictionary's `styles.css`.

Three facts about how Yomitan installs and lays out this sheet drive its shape.

**It is wrapped, not injected.** `Display._getCustomCss` passes each enabled
dictionary's stylesheet through
`addScopeToCss(styles, '[data-dictionary="<title>"]')`, which nests the *entire*
sheet inside that scope. Consequences:

* rules only ever match inside this dictionary's own entries, which is the
  isolation guarantee -- but it also means
* a selector naming an ancestor of the scope cannot work.
  `:root[data-theme=dark] [data-sc-grammar-card]` desugars to
  `[data-dictionary="..."] :root[data-theme=dark] [data-sc-grammar-card]`, and
  `:root` can never be a descendant, so such a rule silently matches nothing.

**Theme is not `prefers-color-scheme`.** Yomitan's palette is keyed off
`:root[data-theme=dark]` (`ext/css/display.css`, `ext/css/material.css`), and a
user can run its dark theme on a light-mode OS. A media-query-only dark palette
therefore leaves light-mode text on a `#1e1e1e` background -- measured at 1.18:1.

Both of those have one answer: derive the card's colours from Yomitan's own
`--text-color` / `--background-color`, which the host already flips with the
active theme. No theme selector is needed, nothing depends on an ancestor of the
scope, and the card tracks any future Yomitan theme for free.

**Wrapping must reduce intrinsic width, not just permit line breaks.**
`overflow-wrap: break-word` lets a long token break during layout but does *not*
lower the element's min-content contribution, and Yomitan's
`.glossary-list-container` is `min-width: auto`. A single unbreakable producer URL
therefore sets the min-content width of every ancestor and pushes the whole card
past the popup edge -- measured at 141px of overhang at a 320px width.
`overflow-wrap: anywhere` is the value that *does* reduce min-content width, and
`min-width: 0` releases the automatic floor, so both are applied across the card.

Design tokens live on this dictionary's preserved `data-sc-*` wrapper rather than
on `:root`, because glossary content renders inside a shadow root that does not
inherit root custom properties.
"""

from __future__ import annotations

from .banks import CARD_ROOT_ROLE

_ROOT = f"[data-sc-{CARD_ROOT_ROLE}]"

#: Interactive target height. WCAG 2.2 SC 2.5.8 sets the floor at 24 CSS px;
#: 28px is chosen so the disclosure rows are comfortable rather than exactly at
#: the limit. Expressed as a single declared minimum instead of a minimum plus
#: padding, so one value provably determines the target size.
_TARGET = "28px"

STYLES_CSS = f"""\
{_ROOT} {{
  --bugd-gap: 0.35em;
  --bugd-target: {_TARGET};
  --bugd-muted: color-mix(in srgb, var(--text-color) 78%, var(--background-color));
  --bugd-rule: color-mix(in srgb, var(--text-color) 55%, var(--background-color));
  display: flow-root;
  line-height: 1.5;
}}

{_ROOT},
{_ROOT} * {{
  overflow-wrap: anywhere;
}}

@media (forced-colors: active) {{
  {_ROOT} {{
    --bugd-muted: CanvasText;
    --bugd-rule: CanvasText;
  }}
}}

{_ROOT} [data-sc-card-headword] {{
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--bugd-gap);
}}

{_ROOT} [data-sc-card-jlpt] {{
  flex: none;
}}

{_ROOT} [data-sc-card-source-label],
{_ROOT} [data-sc-card-source-fact],
{_ROOT} [data-sc-card-field-name],
{_ROOT} [data-sc-card-example-en] {{
  color: var(--bugd-muted);
}}

{_ROOT} [data-sc-card-summary] {{
  min-height: var(--bugd-target);
  border-block-start: 1px solid var(--bugd-rule);
}}
"""


__all__ = ["STYLES_CSS"]
