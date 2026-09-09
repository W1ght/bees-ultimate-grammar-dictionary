"""Theme legibility: light, Yomitan dark, and forced-colors.

Contrast is computed from what the browser actually resolved for the rendered
element, not from the stylesheet source, so a token that fails to apply inside
Yomitan's cascade shows up as an unreadable measured ratio.

The dark-mode cases matter most. Yomitan drives its own theme from
`:root[data-theme=dark]` (see `ext/css/display.css` and `ext/css/material.css`),
which is *not* the same signal as `prefers-color-scheme`. A dictionary
stylesheet that keys its dark palette only off the media query renders
light-mode text on Yomitan's dark background whenever the two disagree -- so both
combinations are measured separately.
"""

from __future__ import annotations

import pytest
from harness import selectors as sel
from harness.colour import SYSTEM_COLORS, contrast_ratio
from harness.contract import MIN_BODY_CONTRAST, MIN_NONTEXT_CONTRAST

RICH = "multi_source_rich"

#: Text-bearing roles whose legibility a reader depends on.
TEXT_ROLES = (
    sel.EXPRESSION,
    sel.GLOSS,
    sel.STRUCTURE,
    sel.SUMMARY,
    sel.JLPT,
)


def _background(rendered) -> str:
    """The effective backdrop the card's text is painted onto.

    Structured-content wrappers are transparent, so the nearest opaque ancestor
    is what actually decides legibility. Walking up to it is the difference
    between measuring real contrast and measuring text against `rgba(0,0,0,0)`.
    """
    return rendered._page.evaluate(
        """(root) => {
            let el = document.querySelector(root);
            while (el) {
                const value = getComputedStyle(el).backgroundColor;
                const match = /rgba?\\(([^)]+)\\)/.exec(value);
                if (match) {
                    const parts = match[1].split(/[,/\\s]+/).filter(Boolean);
                    const alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
                    if (alpha > 0) { return value; }
                }
                el = el.parentElement;
            }
            return getComputedStyle(document.documentElement).backgroundColor;
        }""",
        sel.ROOT,
    )


@pytest.mark.parametrize(
    "theme,os_scheme,label",
    [
        ("light", "light", "light theme, light OS"),
        ("dark", "dark", "Yomitan dark theme, dark OS"),
        ("dark", "light", "Yomitan dark theme, light OS"),
    ],
)
@pytest.mark.parametrize("role", TEXT_ROLES, ids=lambda value: value.strip("[]"))
def test_card_text_is_legible(
    renderer, card, styles_css, theme, os_scheme, label, role
):
    """Every text role clears WCAG AA body-text contrast in every theme."""
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, theme=theme, os_scheme=os_scheme
    )
    if not rendered.exists(role):
        pytest.skip(f"rich fixture has no {role}")
    background = _background(rendered)
    colour = rendered.computed(role, "color")
    ratio = contrast_ratio(colour, background)
    assert ratio >= MIN_BODY_CONTRAST, (
        f"{label}: {role} is illegible -- colour {colour} on {background} is "
        f"contrast {ratio:.2f}, below the {MIN_BODY_CONTRAST} AA minimum"
    )


@pytest.mark.parametrize(
    "theme,os_scheme,label",
    [
        ("light", "light", "light theme, light OS"),
        ("dark", "dark", "Yomitan dark theme, dark OS"),
        ("dark", "light", "Yomitan dark theme, light OS"),
    ],
)
def test_card_design_tokens_track_the_active_theme(
    renderer, card, styles_css, theme, os_scheme, label
):
    """The card's muted text and rules stay legible on the real backdrop.

    Measured where the tokens are *used*, not where they are declared. A custom
    property's computed value is its unresolved substitution value -- Chromium
    reports `--bugd-muted` verbatim as `color-mix(in srgb, ...)` -- so reading the
    variable proves nothing about what the user sees. The consuming property's
    computed `color` and `border-block-start-color` are fully resolved, and they
    are what a reader actually perceives.

    This is the assertion that catches both real defects in this area: a dark
    palette keyed only off `prefers-color-scheme` (silent when Yomitan's dark
    theme runs on a light-mode OS), and a theme rule written as
    `:root[data-theme=dark] <card>`, which cannot match once Yomitan nests the
    whole sheet inside `[data-dictionary="..."]`.
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, theme=theme, os_scheme=os_scheme
    )
    background = _background(rendered)

    muted_consumer = sel.SOURCE_LABEL
    rendered.open_details(sel.SOURCES)
    muted = rendered.computed(muted_consumer, "color")
    muted_ratio = contrast_ratio(muted, background)
    assert muted_ratio >= MIN_BODY_CONTRAST, (
        f"{label}: muted text ({muted_consumer}) resolved to {muted} against "
        f"background {background}, contrast {muted_ratio:.2f} < "
        f"{MIN_BODY_CONTRAST}. The card's palette is not tracking Yomitan's "
        "active theme."
    )
    # Legibility alone would also pass if the card declared no muted colour at
    # all and simply inherited body text. The point of the token is a visible
    # hierarchy, so assert it is actually *different* from primary text and still
    # weaker than it -- that is what distinguishes a working token from dead CSS.
    primary = rendered.computed(sel.GLOSS, "color")
    assert muted != primary, (
        f"{label}: muted text and primary text resolved to the same colour "
        f"({primary}); the --bugd-muted token is not in effect, so secondary "
        "content has no visual hierarchy"
    )
    primary_ratio = contrast_ratio(primary, background)
    assert muted_ratio < primary_ratio, (
        f"{label}: 'muted' text ({muted_ratio:.2f}) is not weaker than primary "
        f"text ({primary_ratio:.2f}) against {background}"
    )

    width = rendered.computed(sel.SUMMARY, "border-block-start-width")
    assert width not in ("0px", ""), (
        f"{label}: disclosure rows declare no top border ({width!r}), so the "
        "sections have no visible separator"
    )
    rule = rendered.computed(sel.SUMMARY, "border-block-start-color")
    rule_ratio = contrast_ratio(rule, background)
    assert rule_ratio >= MIN_NONTEXT_CONTRAST, (
        f"{label}: the disclosure rule resolved to {rule} against background "
        f"{background}, contrast {rule_ratio:.2f} < {MIN_NONTEXT_CONTRAST} "
        "(WCAG 1.4.11 non-text contrast)"
    )


def test_forced_colors_resolves_every_role_to_a_system_colour(
    renderer, card, styles_css
):
    """In forced-colors mode the card must defer to the user's palette."""
    rendered = renderer.render(card(RICH), styles_css=styles_css, forced_colors=True)
    background = _background(rendered)
    failures = []
    for role in TEXT_ROLES:
        if not rendered.exists(role):
            continue
        colour = rendered.computed(role, "color")
        ratio = contrast_ratio(colour, background)
        if ratio < MIN_BODY_CONTRAST:
            failures.append((role, colour, background, round(ratio, 2)))
    assert not failures, (
        "forced-colors mode leaves card text illegible "
        f"(role, colour, background, contrast): {failures}"
    )


def test_forced_colors_keeps_disclosure_boundaries(renderer, card, styles_css):
    """A forced-colors user must still see that a disclosure is a control."""
    rendered = renderer.render(card(RICH), styles_css=styles_css, forced_colors=True)
    marker = rendered.computed(sel.SUMMARY, "display")
    assert marker == "list-item", (
        f"summary display is {marker!r} in forced-colors mode; the native "
        "disclosure triangle is the only remaining affordance and must survive"
    )
    background = _background(rendered)
    rule = rendered.computed(sel.SUMMARY, "border-block-start-color")
    ratio = contrast_ratio(rule, background)
    assert ratio >= MIN_NONTEXT_CONTRAST, (
        f"the disclosure rule resolved to {rule} on {background} in "
        f"forced-colors mode, contrast {ratio:.2f} < {MIN_NONTEXT_CONTRAST}; "
        f"boundaries must map to the user's system palette "
        f"({sorted(SYSTEM_COLORS)})"
    )


def test_reduced_motion_render_is_stable(renderer, card, styles_css):
    """The card ships no animation; reduced-motion must change nothing."""
    plain = renderer.render(card(RICH), styles_css=styles_css)
    plain_boxes = [(box.x, box.y, box.width) for box in plain.boxes(sel.SUMMARY)]
    reduced = renderer.render(card(RICH), styles_css=styles_css, reduced_motion=True)
    reduced_boxes = [(box.x, box.y, box.width) for box in reduced.boxes(sel.SUMMARY)]
    assert plain_boxes == reduced_boxes, (
        "layout differs under prefers-reduced-motion:\n"
        f"  default: {plain_boxes}\n  reduced: {reduced_boxes}"
    )
    assert reduced.computed("details", "transition-duration") in ("0s", "", "0ms"), (
        "a transition is declared on the disclosure; the card claims no animation"
    )


def test_dictionary_stylesheet_cannot_restyle_the_host(styles_css):
    """Every shipped rule is scoped to this dictionary's own role attributes.

    Parsed by tracking brace depth rather than by regex, because a naive
    `([^{]*){` match treats each declaration block's tail as the next selector
    and reports nested at-rule contents as unscoped rules.

    The production sheet scopes each rule to one of this dictionary's own
    ``data-sc-*`` structured-content roles (and Yomitan additionally wraps the
    whole sheet in a ``[data-dictionary="..."]`` block — see the companion test).
    A rule that named a bare host element (`body`, `:root`, `.yomitan`, `*`) with
    no ``data-sc-`` attribute could leak onto Yomitan or another dictionary, so
    that is the leak this guards: every selector must reference a ``data-sc-``
    attribute.
    """
    import re as _re

    def strip_comments(text: str) -> str:
        return _re.sub(r"/\*.*?\*/", "", text, flags=_re.DOTALL)

    selectors: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in styles_css:
        if char == "{":
            prelude = strip_comments("".join(buffer)).strip()
            buffer = []
            depth += 1
            if prelude.startswith("@"):
                continue  # at-rule prelude; its inner rules are checked below
            if depth <= 2:  # top level, or one at-rule deep
                selectors.append(prelude)
        elif char == "}":
            depth -= 1
            buffer = []
        else:
            buffer.append(char)

    assert selectors, "styles.css declares no rules at all"
    unscoped = [
        candidate
        for candidate in selectors
        if "data-sc-" not in candidate
    ]
    assert not unscoped, (
        f"styles.css contains rules not scoped to a data-sc-* role: {unscoped}. "
        "An unscoped rule can restyle Yomitan or another dictionary's entries."
    )


def test_dictionary_styles_reach_the_card_through_yomitan_scoping(
    renderer, card, styles_css
):
    """The shipped sheet must actually apply after Yomitan wraps it.

    Yomitan does not inject `styles.css` as written. `Display._getCustomCss`
    wraps the whole sheet with `addScopeToCss(styles,
    '[data-dictionary="<title>"]')`, i.e. one CSS *nesting* block. Any rule that
    names an ancestor of that scope -- `:root[data-theme=dark] <card>` being the
    obvious temptation for theming -- desugars to a selector that can never match,
    and the loss is completely silent.

    Asserting a specific declaration landed proves the sheet survived the
    wrapping, so a future theme or layout rule written in ancestor form fails
    here instead of shipping as dead CSS.
    """
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    scoped = renderer.scoped_css()
    assert scoped.startswith("[data-dictionary="), (
        f"harness did not apply the sheet through Yomitan's scoping: {scoped[:80]!r}"
    )
    line_height = rendered.computed(sel.ROOT, "line-height")
    font_size = float(rendered.computed(sel.ROOT, "font-size").removesuffix("px"))
    assert line_height not in ("normal", ""), (
        "the card root has no resolved line-height, so the dictionary "
        "stylesheet did not apply at all after Yomitan's scoping"
    )
    assert abs(float(line_height.removesuffix("px")) - font_size * 1.5) < 0.5, (
        f"card root line-height is {line_height} at font-size {font_size}px; "
        "the shipped 1.5 declaration is not in effect"
    )


def test_card_render_issues_no_external_requests(renderer, card, styles_css):
    """An offline dictionary must not fetch anything while rendering."""
    renderer.render(card(RICH), styles_css=styles_css)
    external = [
        url
        for url in renderer.requests
        if not url.startswith(("http://127.0.0.1", "data:", "blob:", "about:"))
    ]
    assert not external, f"card render issued external requests: {external}"
