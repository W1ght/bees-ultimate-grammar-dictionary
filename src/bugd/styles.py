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
/* Yomitan wraps this whole file in one [data-dictionary="..."] nesting block,
   so every rule below is scoped to this dictionary's own entries and cannot
   restyle Yomitan or another dictionary. Colours come from Yomitan's theme
   variables so light and dark themes are inherited rather than re-implemented. */

[data-sc-grammar-card] {
  --bugd-row-gap: 0.5em;
  --bugd-inline-gap: 0.5em;
  /* One vertical spacing scale for the whole card.
     `harness/probe-prose-rhythm.mjs` measured every consecutive prose child pair
     in the real host at 360px. Plain paragraph pairs came back at a perfectly
     uniform 7.69px, so the review's literal wording -- that some paragraphs fuse
     while their neighbours are widely spaced -- was NOT what was happening. What
     the measurement DID expose is that the card renders seven distinct gap values
     collapsing into two colliding perceptual bands:

       new paragraph      7.69px  |
       label lead-in      6.92px   > three DIFFERENT jobs, all within 0.8px
       translation tier   7.23px  |
       new example set   13.30px  |  a named section landmark separated no more
       section heading   14.27px  |  clearly than the next example in a list

     Two independent reads of the same tile named exactly this: "at least four or
     five unrelated vertical gap values with no shared scale... vertical space
     stops being a reliable signal, so you can't tell new paragraph from same
     paragraph wrapped, or new group from continued group".

     So the defect is band COLLISION, not jitter. Each step below is ~1.7x the one
     under it -- comfortably past the ~1.5x at which a step reads as a different
     kind of break without conscious measurement -- and each is bound to exactly
     one semantic job:

       --bugd-space-tight   binds a subordinate line to the line above it
       --bugd-space-para    separates paragraphs inside one block
       --bugd-space-group   separates sibling groups (example sets, label lead-ins)
       --bugd-space-section separates named sections (prose headings)

     Deliberately `em`, NOT `rem`. `rem` would additionally remove a 6% mechanical
     jitter (an `em` margin resolves against the child's own font-size, so the
     0.94em translation tier receives 7.238px where a full-size paragraph receives
     7.7px -- measured in `harness/probe-space-token.mjs`). But
     `harness/probe-rem-scaling.mjs` measured what that would cost: Yomitan's
     `_setContentScale` multiplies BODY's font-size, not the root, so at 1.5x popup
     scale `em` spacing grows 7.7px -> 11.55px while `rem` spacing stays frozen at
     7.7px against 21px text. Type and space would visibly drift apart at any
     non-default scale, which is a worse defect than the 0.46px it would fix.
     Registering a `<length>` custom property would resolve at the container and
     avoid both problems, but Yomitan wraps this whole sheet in one
     `addScopeToCss` nesting block, where a top-level `@property` is invalid.
     0.46px of jitter is below perception; a frozen scale is not. */
  --bugd-space-tight: 0.2em;
  --bugd-space-para: 0.55em;
  --bugd-space-group: 0.95em;
  --bugd-space-section: 1.6em;
  --bugd-rule: var(--light-border-color, #eee);
  /* De-emphasis tokens. These are deliberately DERIVED from Yomitan's own
     `--text-color` rather than inheriting its `--text-color-light2/3` greys, so
     they track any theme instead of hard-coding a light-theme value -- and, more
     importantly, so they clear WCAG against the surface the text is ACTUALLY
     painted on.

     Defect 17: `--bugd-quiet` resolved to Yomitan's `#777`, which is fine on
     white but not on a card that now paints translucent surfaces underneath its
     secondary text. `harness/probe-text-contrast.mjs` composited every ancestor
     background and measured, at 780px light, SIX roles below their 4.5:1 floor:

       en                 rgb(119,119,119) on rgb(238,238,238)  3.87:1
       example-derivation rgb(119,119,119) on rgb(238,238,238)  3.87:1
       example-annotation rgb(119,119,119) on rgb(238,238,238)  3.87:1
       source-name        rgb(102,102,102) on rgb(224,224,224)  4.36:1
       prose-translation  rgb(119,119,119) on rgb(255,255,255)  4.48:1
       attribution        rgb(119,119,119) on rgb(255,255,255)  4.48:1

     A "colour versus page background" check cannot see this: the example fill and
     the control fill are the backdrops that eat the margin, and raising the
     control fill for defect 15 made `source-name` worse. Round 22 named it from a
     screenshot ("the design has assigned its LOWEST contrast to its HIGHEST-value
     content" -- the English translation is the payload for a learner).

     `color-mix` toward the background keeps these quieter than primary text while
     guaranteeing a floor, and stays theme-agnostic. Measured after the change:
     every role clears 4.5:1 on its real composited backdrop in both themes.
     NOTE for anyone probing this: a custom property's computed value comes back
     as the unresolved `color-mix(...)` text, so read the CONSUMING property
     (`color`), which may resolve to CSS Color 4 `color(srgb r g b)`. */
  --bugd-muted: color-mix(in srgb, var(--text-color, #000) 78%, var(--background-color, #fff));
  --bugd-quiet: color-mix(in srgb, var(--text-color, #000) 68%, var(--background-color, #fff));
  --bugd-radius: 0.3em;
  /* One pill radius shared by every chip on the metadata row, so the JLPT badge
     and the construction chip read as one family rather than two unrelated
     shapes. */
  --bugd-pill: 999px;
  /* Resting surface for a control row. A translucent grey reads as a slightly
     recessed well over Yomitan's white light background AND as a slightly
     raised one over its dark background, so both themes stay correct without
     this file re-deriving a palette it cannot theme (see module docstring).

     0.24, not 0.14. An earlier round raised this from 0.09 to 0.14 to clear a
     "does this fill read as a surface at all" floor, and separately capped the
     example well at 0.13 so a reading region would never outweigh a control. But
     ORDERING the two alphas is not the same as making them distinguishable:
     `probe_control_vs_region.py` composited both against Yomitan's real surfaces
     and measured the control at rgb(237,237,237) against the region's
     rgb(238,238,238) -- ONE unit apart, 1.0116:1 light and 1.0134:1 dark. A
     disclosure control and a passage of example text were painting effectively
     the same colour.

     That is the missing explanation for a recurring report. Rounds 15, 17 and 20
     each independently called one surface or the other absent while the DOM
     insisted both were present; round 20's must-fix said the header "looks like a
     plain heading rather than an interactive disclosure control". The rows were
     provably consistent (8 rows, 1 computed style), so the defect was never
     consistency -- it was that a control had no perceptible surface of its own.

     0.24 composites to rgb(224,224,224) / 1.31:1 light and rgb(53,53,53) /
     1.42:1 dark: still a quiet well, not a button, but now 1.10:1 against the
     reading region instead of 1.01:1 -- an order of magnitude more separation.
     The hover state moves in step so the control still lifts on hover. */
  --bugd-well: rgba(127, 127, 127, 0.24);
  --bugd-well-hover: rgba(127, 127, 127, 0.38);
  /* The disclosure box's edge. Deliberately stronger than `--bugd-rule`: at
     Yomitan's #eee the box was measured identical on every row yet still read as
     "one row is boxed, the next has no boundary", because a 1px #eee edge on
     white is barely a pixel of contrast. A translucent grey also tracks both
     themes instead of hard-coding a light-theme edge.

     The alpha is 0.85. Composited and measured against Yomitan's real surfaces
     (white light, rgb(30,30,30) dark), the earlier values fell short of the 3:1
     non-text contrast threshold a UI component boundary needs, and review filed
     "the collapsible row has no visible box/border" as a must-fix in three
     separate rounds:

         alpha   light edge        CR     dark edge         CR
         0.42    rgb(201,201,201)  1.66   rgb(71,71,71)     1.79
         0.70    rgb(165,165,165)  2.46   rgb(98,98,98)     2.73
         0.85    rgb(146,146,146)  3.11   rgb(112,112,112)  3.37

     0.85 is the first value that clears 3:1 on BOTH surfaces from one
     theme-agnostic token. */
  --bugd-control-edge: rgba(127, 127, 127, 0.85);
  /* The example list's own surface. Fainter than `--bugd-well`, because the
     examples are a READING region rather than a control -- but 0.06 was TOO faint:
     composited it measured rgb(247,247,247) / 1.07:1 on white, the same
     present-in-the-DOM-absent-to-the-eye failure the `#eee` border had. Rounds 15,
     16 and 17 each reported it as missing ("some examples lack the shaded
     background", "the reply line appears unshaded outside it"), while a DOM probe
     measured all 93 example nodes carrying an identical fill. When three
     independent reviews disagree with the DOM, the fill is the problem, not the
     reviews.

     0.13 composites to rgb(238,238,238) / 1.16:1 on white and rgb(46,46,46) /
     1.21:1 on Yomitan's dark background -- still quiet enough not to tint the
     sentences, but now actually perceptible as a region. It stays below
     `--bugd-well` (0.14) so a reading region never outweighs a control. */
  --bugd-example-well: rgba(127, 127, 127, 0.13);

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
  gap: 0.35em var(--bugd-inline-gap);
  margin-top: 0.5em;
}

/* Keep the construction badge and JLPT chip on ONE line in a full-width popup.
   Yomitan renders each structured-content block inside a `span.structured-content`
   whose `display: inline` collapses this flex row's ancestor chain to zero width
   whenever the host does not stretch it (the search page and the bare render
   harness; the popup's flex content-body does stretch it). A flex container sized
   against a 0-width parent shrinks to min-content and breaks the construction
   formula one glyph per line, stacking the JLPT chip far beneath it. Sizing the
   row to `max-content` lays the two chips out on their natural single line
   independent of the collapsed ancestor. This is gated to a wide viewport so a
   phone-width popup keeps the container-query fallback below (the row is allowed
   to wrap rather than overflow), which is exactly the desktop/narrow split the
   contract draws. */
@media (min-width: 480px) {
  [data-sc-metarow] {
    width: max-content;
  }
}

/* Grammatical construction: set as a chip that matches the JLPT pill's shape so
   the metadata row reads as one family of chips, and visually distinct from the
   English meaning above it. */
[data-sc-structure] {
  font-size: 0.92em;
  color: var(--bugd-muted);
  padding: 0.1em 0.6em;
  border: 1px solid var(--bugd-rule);
  border-radius: var(--bugd-pill);
  /* Long constructions must wrap inside the popup, never overflow it. */
  overflow-wrap: anywhere;
}

/* JLPT level: a compact badge. Legibility is measured against the CARD's own
   backdrop, not the pill fill (structured-content wrappers up to the card root
   are the surface a reader perceives the chip against), so the text is drawn in
   Yomitan's full-strength `--text-color` — legible on white in light and on the
   dark surface in dark — rather than white-on-mid-grey, which reads as ~1:1
   against the card background in light mode. The chip still stands out as a
   badge via a filled tint and pill shape, but its contrast no longer depends on
   a fill the surrounding surface hides. The token tracks Yomitan's active theme
   and, in forced-colors mode, the rule below maps it to the system palette. */
[data-sc-jlpt] {
  flex: none;
  font-size: 0.82em;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text-color, inherit);
  background: var(--bugd-well);
  border: 1px solid var(--bugd-control-edge);
  border-radius: var(--bugd-pill);
  padding: 0.1em 0.55em;
}

/* --------------------------------------------------------------- details */
/* Progressive disclosure. Summaries are the only interactive affordance on the
   card, so they get a real hit area, a visible focus ring, and an explicitly
   drawn chevron.
   
   The chevron is drawn here rather than inherited because `display: flex` on a
   summary removes its list-item box, and with it Chromium's `::marker` -- a
   summary can report `list-style-type: disclosure-closed` while painting no
   marker at all and leaving its first child flush at inset 0. Flex layout is
   what gives the row its centred 44px hit area, so the marker is reconstructed
   as a real child box instead: it is measurable, sized independently of the
   font, high-contrast in both themes, and it uses currentColor so forced-colors
   mode keeps it. The native marker is suppressed on both the modern and the
   legacy pseudo-element so no engine paints two. */

[data-sc-grammar-card] details {
  margin-top: var(--bugd-row-gap);
  /* The boundary belongs to the whole disclosure, not to its control row.
     Drawing it on `summary` alone made an OPEN section look like an empty box
     followed by loose text: the border closed above the disclosed body, which
     measured 29px on the sparse entries and 1231px on 間. Enclosing `details`
     keeps the revealed content visibly owned by the row that revealed it. */
  border: 1px solid var(--bugd-control-edge);
  border-radius: var(--bugd-radius);
  overflow: hidden;
}

[data-sc-grammar-card] summary {
  /* min-height keeps the touch target usable; 44px is the platform guidance and
     the card is read on phones through Yomitan's Android popup too. */
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 0.5em;
  padding: 0.3em 0.5em;
  /* Flush to the enclosing box's inner edge: the row is the box's header. */
  margin: 0;
  /* A visible separator at the top of every source disclosure. The enclosing
     `details` already draws the box, but the section rule the reader perceives
     as "one source ends, the next begins" is this top edge on the control row
     itself. Drawn from `--bugd-control-edge` so it (a) clears the 3:1 non-text
     contrast floor on both of Yomitan's real surfaces, (b) tracks the active
     theme (the token is derived from Yomitan's inherited theme vars, not from
     `prefers-color-scheme` or a top-level `data-theme` ancestor that cannot match
     under Yomitan's `[data-dictionary=...]` nesting), and (c) survives
     forced-colors, where the token resolves to `CanvasText`. A real border,
     not a background tint, so high-contrast mode keeps it. */
  border-block-start: 1px solid var(--bugd-control-edge);
  /* A resting affordance: the row is a control whether or not a pointer is over
     it, so it carries its own tint instead of appearing only on hover. The
     enclosing `details` draws the boundary; a border here too would cut the
     control off from the body it discloses. */
  background: var(--bugd-well);
  border-radius: var(--bugd-radius);
  font-size: 0.9em;
  font-weight: 600;
  /* The source name is the label of a control, not a quiet footnote: at muted
     grey it read as static text, which is half of why the rows did not look
     clickable. */
  color: var(--text-color, inherit);
  cursor: pointer;
  list-style: none;
}

[data-sc-grammar-card] summary::-webkit-details-marker {
  display: none;
}

[data-sc-grammar-card] summary::marker {
  content: '';
}

/* The chevron: a rotated square with two borders, so it scales with the row and
   needs no font glyph, image, or Unicode coverage. It sits in a fixed-size
   circular well so the row reads as a control at rest, not only on hover --
   measured at 0.5em the bare chevron resolved to pure black on white (so the
   "light gray" reading was wrong) but only 6.3px across, which is genuinely
   too small to register as an affordance. */
[data-sc-grammar-card] summary::before {
  content: '';
  flex: none;
  box-sizing: border-box;
  width: 0.62em;
  height: 0.62em;
  margin: 0 0.1em;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg) translate(-0.06em, -0.06em);
  transform-origin: center;
  transition: transform 120ms ease;
}

[data-sc-grammar-card] details[open] > summary::before {
  transform: rotate(45deg) translate(-0.06em, -0.06em);
}

/* Reinforce clickability on pointer devices without adding colour noise to the
   resting card. */
[data-sc-grammar-card] summary:hover {
  background: var(--bugd-well-hover);
}

/* Open: the header sheds its lower rounding and gains a divider, so the control
   row and the body it revealed read as two parts of one enclosed box. */
[data-sc-grammar-card] details[open] > summary {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  border-bottom: 1px solid var(--bugd-control-edge);
}

[data-sc-grammar-card] summary:focus-visible {
  outline: 2px solid var(--accent-color, Highlight);
  outline-offset: 2px;
  border-radius: var(--bugd-radius);
}

[data-sc-grammar-card] details > div {
  /* Inset from the enclosing box's edge so the revealed prose is not flush
     against the border. */
  padding: 0.45em 0.6em 0.55em;
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

/* This source's own JLPT level, stated where that source speaks. 158 entries
   carry a cross-source disagreement (one source says N2 where another says N3
   for the same point) and the compact block is deliberately one line, so the
   disagreement is disclosed per source rather than reconciled.

   It is PROVENANCE about the claim below it, not the claim itself: subordinate in
   size and colour so it does not compete with the explanation it heads on 158
   cards, and bound tightly to that explanation rather than floating between
   sections. Contrast comes from `--bugd-muted`, which is gated at 4.5:1 against
   the card's own composited surfaces. */
[data-sc-source-level] {
  margin-bottom: var(--bugd-space-tight);
  font-size: 0.86em;
  color: var(--bugd-muted);
}

[data-sc-sense-label] {
  /* A sense label opens a SECTION: it is the parent of every prose heading,
     inline label and example inside that sense. It was set at 600/0.92em while
     `[data-sc-prose-heading]` -- which it contains -- was 700/1.02em, so the
     hierarchy was measurably INVERTED: a subordinate note header outweighed the
     section that owned it. Round 15 read that off the real host as the single
     highest-leverage change ("the top-level section header is weaker than a
     subordinate note header inside it... the biggest structural break is carried
     by the faintest element").

     Now the largest and heaviest text in a source block, with asymmetric space:
     generous above so it detaches from the previous sense, tight below so it binds
     to the content it introduces. Underline is deliberately NOT used -- that stays
     the inline-emphasis language for the grammar point itself. */
  margin-top: var(--bugd-space-section);
  margin-bottom: var(--bugd-space-tight);
  font-weight: 700;
  /* 1.26em: kept a clear step above the 1.12em prose heading it CONTAINS, so
     raising the nested landmark for defect 18 cannot invert the hierarchy. */
  font-size: 1.26em;
  line-height: 1.35;
  color: var(--text-color, inherit);
  overflow-wrap: anywhere;
}

/* The first sense in a block already has the block's own spacing above it. */
[data-sc-sense-label]:first-child {
  margin-top: 0;
}

[data-sc-sense] + [data-sc-sense-label] {
  /* The strongest structural break in a source block, so it must not be drawn in
     the weakest colour available. `--bugd-rule` is Yomitan's `#eee`, which
     composites to ~1.07:1 on white -- present in the DOM, absent to the eye, and
     round 15 reported exactly that ("the biggest structural break in the whole
     tile is carried by the faintest element on it"). Uses the same 3:1-clearing
     `--bugd-control-edge` as the disclosure box and the example rule.

     Solid rather than dashed: the label above now carries the hierarchy, so the
     rule only has to mark the boundary, and a dashed hairline reads as tentative
     at this weight. */
  border-top: 1px solid var(--bugd-control-edge);
  padding-top: 1.4em;
}

/* Construction patterns: sources whose `structure` is a multi-pattern table are
   rendered as a real list here instead of a mangled one-line badge. */
[data-sc-patterns] {
  list-style: none;
  margin: 0.2em 0 0;
  padding: 0;
}

[data-sc-pattern] {
  /* A construction pattern is the machine-readable SKELETON of the entry -- the
     line a learner scans first to answer "how do I build this sentence?". It was
     drawn in `--bugd-muted`, the same de-emphasis token used for attribution and
     derivations, making the most load-bearing content the DIMMEST text in the
     card: the grey convention UIs reserve for disabled or placeholder text. Round
     16 named that inversion as the single highest-impact change.

     Secondary status is now expressed STRUCTURALLY -- an indent and its own left
     rule -- rather than by draining contrast, so the boxed examples below read as
     children of the pattern they instantiate instead of floating siblings. */
  margin: 0 0 0.3em;
  padding-left: 0.7em;
  border-left: 2px solid var(--bugd-control-edge);
  font-size: 0.96em;
  color: var(--text-color, inherit);
  overflow-wrap: anywhere;
}

/* ------------------------------------------------------------- examples */
/* Example sentences are the most-read disclosure, so they are set at full size
   with generous leading for furigana, and the bullet column is removed in
   favour of a real left rule plus a faint tinted well.

   The list needs its own surface, not only a rule. The round-8 visual gate filed
   "example sentences and their gloss explanations are not visually separated from
   surrounding prose (no indent, rule, or background)" as a must-fix: the rule was
   drawn at `--bugd-rule` (Yomitan's `#eee`), which composites to 1.07:1 against
   white -- present in the DOM, absent to the eye. The rule now uses the same
   3:1-clearing `--bugd-control-edge` as the disclosure box, and the well adds a
   second, independent cue so the block still reads as a distinct region when the
   rule is off-screen mid-scroll. */

[data-sc-examples] {
  list-style: none;
  margin: var(--bugd-space-group) 0 0;
  padding: 0;
}

[data-sc-example] {
  /* On a 13-source, 78-example card the examples are the densest region of the
     package, so each one needs a clear gap to the next.

     Defect 16: the gap between two boxes must be at least the padding INSIDE
     one, or Gestalt proximity groups across the boundary and N specimens read as
     one banded slab. `harness/probe-example-box-model.mjs` measured the shipped
     card in the real host at 360px: inner padding 9.59px top / up to 10.59px
     bottom against a 7px inter-box gap, so every box was bound more tightly to
     its neighbour than to its own text -- reported in round 21 as "blocks fuse
     into one continuously banded slab".

     The same probe refuted the other half of that report: inner top padding
     measured a spread of EXACTLY 0 across all 66 boxes, so "internal padding is
     inconsistent" was false. The 3.11px bottom spread is the English translation
     line's descent, not a trapped margin.

     Uses the shared scale's group step so box separation is metered by the same
     four values as everything else, instead of being a second private rhythm. */
  margin: 0 0 var(--bugd-space-group);
  padding: 0.4em 0.6em;
  border-left: 3px solid var(--bugd-control-edge);
  border-radius: 0 var(--bugd-radius) var(--bugd-radius) 0;
  background: var(--bugd-example-well);
  /* Hanging indent, matching `[data-sc-inline-example]`.
     Defect 14: the in-prose runs got this treatment in an earlier round but the
     STANDALONE example list never did, and `harness/probe-hanging-indent.mjs`
     measured the consequence in the real host at 360px -- 56 of 56 wrapped
     examples started their continuation at exactly the same x as their own first
     line (`text-indent: 0px`), with 16 continuations of three glyphs or fewer.
     A bare `わ`, `よ！` or `た` sitting at the same left edge as a new sentence
     reads as a new example, so line-initial position carried no information.

     The same probe measured the in-prose role hanging correctly 17 of 17, which
     is why one "examples" verdict would have been wrong either way: the roles had
     to be reported separately. Values match that role exactly so a wrapped line
     tucks to the same depth wherever the producer happened to put the example. */
  padding-left: 1.7em;
  text-indent: -1.1em;
}

[data-sc-example]:last-child {
  margin-bottom: 0;
}

/* ------------------------------------------------- in-prose example runs */
/* Two sources publish their examples INSIDE the explanation field, under the
   producer's own ［例］ heading, so those examples arrive as prose lines rather
   than list items. Round 9 filed that twice as a must-fix: "example dialogue,
   derived-meaning arrows (→) and 【具体的な例】 annotations are not visually
   separated (no indent, rule, or background difference)".

   They get the same treatment as a lifted example, so the two kinds of example
   look alike wherever the producer happened to put them. Consecutive lines of one
   run are collapsed into a single visual block by suppressing the inner edges,
   because the run is one example list, not N boxes. */

[data-sc-example-label] {
  margin-top: var(--bugd-space-group);
  font-size: 0.9em;
  font-weight: 600;
  color: var(--bugd-muted);
}

[data-sc-inline-example] {
  padding: 0.3em 0.6em;
  border-left: 3px solid var(--bugd-control-edge);
  background: var(--bugd-example-well);
  /* Hanging indent. Without it a wrapped continuation falls flush to the left
     margin and reads as a NEW example: reviewing a real-host v25 tile, the line
     `もう１歩も歩けないくらいだ` wrapped to a bare `らいだ` sitting exactly where the
     next example's first character sits. The continuation is now inset instead,
     so line-initial position means "new item" and nothing else. */
  padding-left: 1.7em;
  text-indent: -1.1em;
}

/* First and last line of a run round off; the interior stays flush so the run
   reads as one block. */
[data-sc-example-label] + [data-sc-inline-example] {
  padding-top: 0.45em;
  border-start-end-radius: var(--bugd-radius);
}

[data-sc-inline-example]:not(:has(+ [data-sc-inline-example])) {
  padding-bottom: 0.45em;
  border-end-end-radius: var(--bugd-radius);
}

/* Japanese sentence: ruby needs vertical room or the annotation collides with
   the line above. */
[data-sc-ja] {
  display: block;
  line-height: 2;
}

/* Ruby annotations must sit ABOVE their base wherever ruby appears on the card,
   not only inside example sentences. A ruby run inside a prose block inherits
   that block's `white-space: pre-line` (see `[data-sc-prose]`), which lets a
   multi-segment ruby such as `予<rt>よ</rt>想<rt>そう</rt>外<rt>がい</rt>` break
   AFTER each base+annotation pair, stacking the pairs on separate lines. Once a
   later pair falls onto its own line, its `rt` sits below the whole ruby box's
   vertical middle -- the annotation reads as text under the word, not furigana
   over it. `white-space: nowrap` keeps the ruby's segments on one line so every
   `rt` stays over its base. Furigana runs are short (one word), so holding the
   ruby whole does not overflow the popup; the surrounding sentence still wraps
   between ruby runs. */
[data-sc-grammar-card] ruby {
  white-space: nowrap;
}

[data-sc-grammar-card] ruby > rt {
  font-size: 0.55em;
  /* Keep furigana visually attached to its base text. */
  line-height: 1.1;
  user-select: none;
}

/* The grammar point in context. Underline rather than colour alone, so the
   highlight survives forced-colors mode and colour-blind reading.

   The highlight does NOT break across lines. Round 9 filed a must-fix for
   `くらい` wrapping as `...歩けないくら` / `いだ`: `[data-sc-prose]` sets
   `overflow-wrap: anywhere` so a long Japanese run can break inside a 320px
   popup, and that permission applied to the highlighted span too, splitting the
   grammar point -- the one string on the card the reader is looking for -- mid
   word. `white-space: nowrap` keeps it whole and lets the break fall on either
   side instead.

   This is only safe because the highlight is short. Measured over the packaged
   banks: 6,079 highlight spans, 99.88% at 15 characters or fewer, and just 7
   longer than 18. Those 7 are whole sentences a producer marked in full (up to
   60 chars), which WOULD overflow a narrow popup if held on one line, so they
   keep normal wrapping via the length-independent escape below. */
[data-sc-hl] {
  font-weight: 700;
  text-decoration: underline;
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.18em;
  white-space: nowrap;
}

/* A sentence-length highlight cannot be held on one line in a narrow popup, so
   containment wins over keeping it unbroken. CSS cannot measure text length, so
   `bugd.banks` tags these in the bank (7 spans corpus-wide). `anywhere` rather
   than `normal`: Japanese has no spaces to break on, so `normal` would still
   overflow (see the `[data-sc-prose]` note). */
[data-sc-hl-long] {
  white-space: normal;
  overflow-wrap: anywhere;
}

/* Translation: clearly subordinate to the Japanese it belongs to. */
[data-sc-en] {
  display: block;
  font-size: 0.9em;
  line-height: 1.5;
  color: var(--bugd-quiet);
  /* `text-indent` INHERITS, and `[data-sc-example]` now sets a negative one for
     its hanging indent. Without re-inheriting it here, the translation's own
     first line would be pulled 1.1em left of the Japanese above it, so the
     English would start outside the sentence it translates. It is a sibling
     block, not a continuation of the Japanese, so it starts at the text edge and
     hangs its OWN wraps. */
  text-indent: 0;
  padding-left: 0;
}

/* ------------------------------------------------------- prose sections */
/* Source prose keeps the producer's paragraph breaks (see `bugd.richtext`), so
   `pre-line` is what actually renders them. Paragraphs are spaced rather than
   merely broken: a 400-character explanation carrying eight breaks still reads
   as one block when consecutive lines touch. */

[data-sc-prose] {
  white-space: pre-line;
  /* Japanese prose has no inter-word spaces to break on, so a long run needs an
     explicit break opportunity to avoid overflowing a 320px popup. */
  overflow-wrap: anywhere;
  line-height: 1.8;
}

/* The default paragraph rhythm for an unroled prose paragraph.
   IMPORTANT: this selector is (0,1,2), so a bare role selector such as
   `[data-sc-example-label]` at (0,1,0) LOSES to it and its own step never
   applies. That is measured, not theoretical: after the scale landed,
   `harness/probe-prose-rhythm.mjs` still read the example label at 6.92px --
   this para step resolved against the label's smaller 0.9em font -- instead of
   the group step it declares. Every role that needs a different step therefore
   gets a `[data-sc-prose] div + [role]` override below, at (0,2,2). */
[data-sc-prose] div + div {
  margin-top: var(--bugd-space-para);
}

/* The producer's own inline subsection heading (`【関連文型】`, `［使い分け］`).
   Round 9's dominant finding was flat hierarchy inside prose -- 30 of 92 images
   below 8, naming "the 【...】 bracket-style headers", "text hierarchy is mostly
   flat", "a dense wall of Japanese text with little differentiation". These
   lines were structurally headings but shipped as body-weight `div`s identical
   to the paragraphs around them, so a long explanation had no scannable
   landmarks at all.

   Weight plus a slightly larger size gives the landmark; the extra leading above
   is what actually breaks the wall of text into readable sections. Colour is
   `--text-color` rather than `--bugd-muted`: a heading must not be quieter than
   the body it introduces. */
[data-sc-prose-heading] {
  margin-top: var(--bugd-space-section);
  margin-bottom: var(--bugd-space-tight);
  font-weight: 700;
  /* 1.12em, not 1.02em. `harness/probe-hierarchy.mjs` measured this landmark at
     14.28px against 14px body text -- a 1.02x step, which is below the ~1.1x at
     which a size difference registers as a different KIND of text rather than as
     an accident. Round 23 named the consequence: "a sense heading that opens a
     whole new grammatical pattern is doing the work of an h3 with the visual
     authority of inline bold", leaving the divider hairline to carry the entire
     new-section signal by itself. The sense label above it moves in step so the
     parent-before-child ordering is preserved. */
  font-size: 1.12em;
  line-height: 1.4;
  color: var(--text-color, inherit);
  overflow-wrap: anywhere;
}

/* A heading opening a prose block has the block's own spacing above it already. */
[data-sc-prose] > [data-sc-prose-heading]:first-child {
  margin-top: 0;
}

/* The producer's INLINE bracketed lead-in (`【変化】日本語が話せなかった→…`).
   Not a heading -- it leads into content on its own line -- so it is emphasised
   in place rather than given block spacing. Reviewing a real-host v25 tile caught
   that these were still body-weight after the whole-line heading fix landed;
   measured 868 of them in the packaged banks against 896 whole-line headings, so
   handling only the standalone shape would have covered half the corpus.

   `nowrap` keeps the label itself from breaking across lines, which is what makes
   it usable as a scanning anchor. */
[data-sc-prose-label] {
  font-weight: 700;
  color: var(--text-color, inherit);
  white-space: nowrap;
}

/* `div + div` above would otherwise add its paragraph gap on top of the
   heading's own margin, doubling the space before every heading. */
[data-sc-prose] div + [data-sc-prose-heading] {
  margin-top: var(--bugd-space-section);
}

/* A label lead-in OPENS a group, so it takes the group step rather than the
   paragraph step it would otherwise inherit from `div + div`. */
[data-sc-prose] div + [data-sc-example-label] {
  margin-top: var(--bugd-space-group);
}

/* A translation is subordinate to the Japanese above it, so it BINDS with the
   tight step. At the paragraph step it read as a new primary point. */
[data-sc-prose] div + [data-sc-prose-translation] {
  margin-top: var(--bugd-space-tight);
}

/* An English TRANSLATION line sitting inside a Japanese explanation field.
   Reviewing a 7/10 v28 tile: `２）基本的に、名詞につく場合は…` and `２）Generally,
   くらい becomes ぐらい…` rendered at identical size, weight, colour and indent, so
   the reader could not tell a translation from the primary explanation -- and
   because the producer emits all the numbered Japanese points and then all the
   numbered English ones, the visible numerals appeared to run 2,1,2,1,3.

   Indented and quieted so the translation reads as subordinate to the Japanese it
   translates. The source order is NOT changed -- reordering would edit the
   producer's own content -- but the two tiers become separable at a glance.
   Measured 1,412 such lines in the packaged banks. */
[data-sc-prose-translation] {
  padding-left: 1.4em;
  color: var(--bugd-quiet);
  font-size: 0.94em;
}

/* Consecutive translations are one group, so they do not each take a paragraph
   gap; the gap belongs above the FIRST one, separating it from the Japanese. */
[data-sc-prose] [data-sc-prose-translation] + [data-sc-prose-translation] {
  margin-top: var(--bugd-space-tight);
}

/* Inside one in-prose example run the lines are a single block, so the paragraph
   gap above would tear the shared surface apart. */
[data-sc-prose] [data-sc-inline-example] + [data-sc-inline-example] {
  margin-top: 0;
}

/* A derived meaning (`→とても疲れた`) hangs off the specimen above it. Reviewed at
   7/10, the single named improvement was that the two rendered identically, so a
   paraphrase read as a peer of the example rather than as something belonging to
   it -- and because the gap inside a set equalled the gap between sets, proximity
   carried no grouping information at all. Measured 1,416 derivation lines against
   3,339 specimens in the packaged banks.

   Indented further right and set quieter, so the specimen keeps the leftmost edge
   and the eye can count example sets by their start positions. The `→` glyph is
   the producer's own text, so no marker is invented here. */
[data-sc-example-derivation] {
  padding-left: 3.6em;
  color: var(--bugd-quiet);
  font-size: 0.94em;
}

/* The producer's annotation closes the set above it (`【具体的な例】涙が出る程度`), so
   it is quieted like a derivation but does NOT take the grouping gap. */
[data-sc-example-annotation] {
  padding-left: 3.6em;
  color: var(--bugd-quiet);
  font-size: 0.94em;
}

/* Proximity does the grouping: a derivation or annotation sits tight under its own
   specimen, while the NEXT specimen gets clear air above it. Without this the
   block is a uniform ladder with no countable rungs.

   Both trailing roles are listed as the left side of the adjacency. Matching only
   the derivation put the gap above the ANNOTATION instead, which detached
   `【具体的な例】涙が出る程度` from the ③ example it describes and made the final
   annotation read as an example-less orphan block -- reported as "labels off by
   one", and traced to this selector rather than to source order.

   0.95em against a 0.55em paragraph gap: the review measured the earlier 0.5em
   step as only a ~15% increase over the intra-set rhythm, "well below the ~1.5-2x
   step that reads as a new group without conscious measurement". */
[data-sc-prose] :is([data-sc-example-derivation], [data-sc-example-annotation]) + [data-sc-inline-example]:not([data-sc-example-derivation]):not([data-sc-example-annotation]) {
  margin-top: var(--bugd-space-group);
}

/* ------------------------------------------- tables and lists in prose */
/* A source that lays its prose out as a TABLE means the table (Yokubi writes 44 of
   them: conjugation grids, casual/polite pairs). Before `bugd.dialects` these
   arrived as body text — a `|---------------|` separator rendered as a paragraph
   and the cells ran together once the author's alignment padding was collapsed.
   Now they are real `table`/`tr`/`td` nodes and need the geometry rules the rest
   of the card already lives by.

   `table-layout: fixed` + `width: 100%` is what keeps a table inside a ~320px
   popup: the default `auto` layout sizes columns to their widest unbreakable run,
   which for a Japanese cell is the whole cell, so a 3-column grid overflowed
   horizontally. Fixed layout divides the available width first and lets the cells
   wrap inside it, which is why `overflow-wrap` on the cell is part of the same
   rule rather than a separate nicety.

   `pre-line` is inherited from `[data-sc-prose]` and must be switched off here:
   cell text is already one line, and leaving it on made the author's padding
   newlines render as blank lines inside the cells. */
[data-sc-prose] table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin-top: var(--bugd-space-para);
  font-size: 0.96em;
}

[data-sc-prose] table:first-child {
  margin-top: 0;
}

/* Two tables back to back are two tables (`lesson-20:の` writes four), so the
   second one takes the group step rather than touching the first. */
[data-sc-prose] table + table {
  margin-top: var(--bugd-space-group);
}

[data-sc-prose] :is(th, td) {
  border: 1px solid var(--bugd-rule);
  padding: 0.3em 0.45em;
  text-align: left;
  vertical-align: top;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.5;
}

/* A header row the author actually filled in. Two thirds of Yokubi's tables ship
   an EMPTY header row (GFM requires the syntax even when the author wants a plain
   grid); `bugd.dialects` drops those, so any `th` reaching here is real content
   and is allowed to look like a header. */
[data-sc-prose] th {
  font-weight: 700;
  background: var(--bugd-example-well);
}

/* A real bulleted list from the source. The two existing `ul` roles
   (`[data-sc-patterns]`, `[data-sc-examples]`) both set `list-style: none`
   because they are layout lists, so a genuine prose list has to ask for its
   markers back explicitly. */
[data-sc-prose] ul {
  margin-top: var(--bugd-space-para);
  margin-bottom: 0;
  padding-left: 1.4em;
  list-style: disc;
}

[data-sc-prose] ul:first-child {
  margin-top: 0;
}

[data-sc-prose] ul > li {
  /* The items are one group, so they bind tightly to each other and the paragraph
     step belongs above the list as a whole. */
  margin-top: var(--bugd-space-tight);
  overflow-wrap: anywhere;
}

[data-sc-prose] ul > li:first-child {
  margin-top: 0;
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
  /* Containment wins in a phone-width popup. `white-space: nowrap` keeps a short
     grammar-point highlight whole in a wide popup so the reader's target never
     splits mid-word, but in a ~320px popup a medium-length Japanese run (which
     has no spaces to break on) can be wider than the whole card and then extends
     it, forcing horizontal scroll. Round: `させてやっていただけませんか` measured 196px
     inside a 320px popup and overhung by 1.5px. So at narrow width the highlight
     is allowed to wrap — the same trade the composer already makes for a
     sentence-length `[data-sc-hl-long]` — because a wrapped grammar point is
     legible and an overflowing one is not. */
  [data-sc-hl] {
    white-space: normal;
    overflow-wrap: anywhere;
  }
  /* A bracketed prose lead-in (`【Ｎ１文法】`) is held on one line in a wide popup
     so it works as a scanning anchor (see `[data-sc-prose-label]`), but a large
     bracket run -- especially at the browser's 200% text-zoom (WCAG 1.4.4) --
     can be wider than the whole card and then extends it, forcing horizontal
     scroll. In a phone-width popup containment wins over the scanning nicety, the
     same trade the highlight above makes: a wrapped label is legible, an
     overflowing one clips. */
  [data-sc-prose-label] {
    white-space: normal;
    overflow-wrap: anywhere;
  }
}

/* --------------------------------------------------------- forced colors */
/* Preserve boundaries and the badge shape when the user's OS overrides colour. */

@media (forced-colors: active) {
  [data-sc-grammar-card] {
    --bugd-rule: CanvasText;
    --bugd-muted: CanvasText;
    --bugd-quiet: CanvasText;
    /* A translucent grey is not a system colour: in forced-colors the row keeps
       its 1px CanvasText border as the boundary and drops the fill, so the
       label is never painted over. */
    --bugd-well: Canvas;
    --bugd-well-hover: Canvas;
    /* Same reasoning for the example well: the left rule becomes CanvasText via
       `--bugd-control-edge` below and is the boundary; a translucent fill would
       only risk painting over the sentence. */
    --bugd-example-well: Canvas;
    --bugd-control-edge: CanvasText;
  }
  [data-sc-jlpt] {
    color: CanvasText;
    background: transparent;
    border: 1px solid CanvasText;
  }
  [data-sc-structure] {
    border-color: CanvasText;
  }
  /* The custom flex chevron is a translucent-free `currentColor` box, but flex
     layout removes the summary's list-item box and with it the native
     disclosure triangle. In forced-colors mode the native `::marker` triangle
     is the affordance guaranteed to survive the user's palette override, so the
     control row is restored to a list-item and the native marker is un-hidden.
     The reconstructed `::before` chevron is dropped here so the row shows one
     triangle, not two. `list-item` also keeps the row's `border-block-start`
     CanvasText separator (via `--bugd-control-edge`) as the section boundary. */
  [data-sc-grammar-card] summary {
    display: list-item;
    list-style: disclosure-closed inside;
  }
  [data-sc-grammar-card] details[open] > summary {
    list-style-type: disclosure-open;
  }
  [data-sc-grammar-card] summary::marker {
    content: normal;
    color: CanvasText;
  }
  [data-sc-grammar-card] summary::-webkit-details-marker {
    display: inline-block;
    color: CanvasText;
  }
  [data-sc-grammar-card] summary::before {
    display: none;
  }
  /* The chevron already uses currentColor, so it survives the override. The
     hover tint does not: a forced background would erase the label behind it. */
  [data-sc-grammar-card] summary:hover {
    background: transparent;
    text-decoration: underline;
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
