"""Layout geometry across viewports, expansion states, and zoom.

Every assertion is a measurement against the popup's own frame, so a failure
names the offending selector plus the two numbers that disagree. Overflow is
reported for the whole card in one pass and blamed on the leaf that cannot wrap,
because an ancestor is only ever as wide as its widest unbreakable descendant.
"""

from __future__ import annotations

import pytest

from harness import selectors as sel
from harness.contract import OVERFLOW_TOLERANCE_PX, ZOOMED_ROOT_FONT_PX

RICH = "multi_source_rich"

#: Fixtures chosen for the layout stress they apply, not for coverage theatre.
LAYOUT_FIXTURES = (
    RICH,  # 26 contributions, 125 examples, 26 variants
    "english_gloss",  # all five JLPT badges in one headword row
    "longest_expression",  # させてやって頂けませんか — longest headword in the corpus
    "most_variants",  # 27 variant links
    "ruby_furigana",  # nested ruby/rt inside example sentences
    "sparse_minimal",  # a single contribution, no examples
)


def _assert_contained(rendered, context: str) -> None:
    rows = rendered.overflow_report()
    assert not rows, f"{context}: {rendered.describe_overflow(rows)}"


@pytest.mark.parametrize("viewport_name", ["desktop", "narrow"])
@pytest.mark.parametrize("name", LAYOUT_FIXTURES)
def test_card_fits_the_popup_when_collapsed(
    renderer, card, styles_css, viewport, viewport_name, name
):
    """The default lookup view never overflows the popup horizontally."""
    rendered = renderer.render(
        card(name), styles_css=styles_css, viewport=viewport(viewport_name)
    )
    _assert_contained(rendered, f"{name} @ {viewport_name}, collapsed")


@pytest.mark.parametrize("viewport_name", ["desktop", "narrow"])
@pytest.mark.parametrize(
    "section",
    [sel.EXAMPLES, sel.EXPLANATION, sel.ALSO_WRITTEN, sel.SOURCES],
    ids=["examples", "explanation", "also_written", "sources"],
)
def test_card_fits_the_popup_when_a_section_is_expanded(
    renderer, card, styles_css, viewport, viewport_name, section
):
    """Expanding a disclosure must not widen the card past the popup.

    `Sources` is the section that historically broke this: producer URLs are long
    unbreakable tokens, and an anchor that cannot wrap sets the width of every
    ancestor up to the card root.
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport(viewport_name)
    )
    if not rendered.exists(section):
        pytest.skip(f"rich fixture has no {section} section")
    rendered.open_details(section)
    _assert_contained(rendered, f"{RICH} @ {viewport_name}, {section} expanded")


@pytest.mark.parametrize("viewport_name", ["desktop", "narrow"])
def test_card_fits_the_popup_when_fully_expanded(
    renderer, card, styles_css, viewport, viewport_name
):
    """The worst case: every disclosure open at once."""
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport(viewport_name)
    )
    rendered.open_all_details()
    _assert_contained(rendered, f"{RICH} @ {viewport_name}, fully expanded")


def test_card_fits_the_popup_at_200_percent_text_zoom(
    renderer, card, styles_css, viewport
):
    """Large-text users (WCAG 1.4.4) must not get a horizontally clipped card."""
    rendered = renderer.render(
        card(RICH),
        styles_css=styles_css,
        viewport=viewport("narrow"),
        font_size=ZOOMED_ROOT_FONT_PX,
    )
    _assert_contained(
        rendered, f"{RICH} @ narrow, root font-size {ZOOMED_ROOT_FONT_PX}px"
    )


def test_long_source_urls_wrap_rather_than_extend(renderer, card, styles_css, viewport):
    """The specific mechanism: producer links must be breakable.

    Asserted as a property of the rendered anchor rather than only as an absence
    of overflow, so the fix cannot be a clip that hides the URL's tail.
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport("narrow")
    )
    rendered.open_details(sel.SOURCES)
    if not rendered.exists(f"{sel.SOURCE_LINK} a"):
        pytest.skip("rich fixture carries no producer links")
    root_width = rendered.box(sel.ROOT).width
    widths = [round(box.width, 1) for box in rendered.boxes(f"{sel.SOURCE_LINK} a")]
    too_wide = [width for width in widths if width > root_width + OVERFLOW_TOLERANCE_PX]
    wrap = rendered.computed(f"{sel.SOURCE_LINK} a", "overflow-wrap")
    overflow = rendered.computed(f"{sel.SOURCE_LINK} a", "overflow")
    assert not too_wide, (
        f"producer link anchors are wider than the card root ({root_width}px): "
        f"{too_wide}; anchor overflow-wrap={wrap!r}. A long URL must wrap, "
        "not extend the card."
    )
    assert overflow in ("visible", ""), (
        f"producer links are contained by clipping (overflow={overflow!r}), "
        "which hides the end of the URL instead of wrapping it"
    )


def test_variant_links_wrap_into_the_narrow_card(
    renderer, card, styles_css, viewport
):
    """27 `?query=` variant links must reflow, not form one long row."""
    rendered = renderer.render(
        card("most_variants"), styles_css=styles_css, viewport=viewport("narrow")
    )
    rendered.open_details(sel.ALSO_WRITTEN)
    anchors = rendered.boxes(f"{sel.VARIANT} a")
    assert len(anchors) >= 10, (
        f"fixture 'most_variants' rendered only {len(anchors)} variant links"
    )
    rows = len({round(box.y, 0) for box in anchors})
    assert rows > 1, (
        f"all {len(anchors)} variant links sit on one row at narrow width; "
        "the list is not wrapping"
    )
    _assert_contained(rendered, "most_variants @ narrow, Also written expanded")


def test_furigana_ruby_sits_above_its_base_text(renderer, card, styles_css):
    """Ruby annotations must align over their base, not inline beside it."""
    rendered = renderer.render(card("ruby_furigana"), styles_css=styles_css)
    rendered.open_details(sel.EXAMPLES)
    assert rendered.count("ruby") > 0, "ruby fixture rendered no <ruby> element"
    assert rendered.count("rt") > 0, "ruby fixture rendered no <rt> annotation"
    misaligned = []
    for index in range(rendered.count("rt")):
        annotation = rendered.box("rt", index)
        base = rendered._page.locator("rt").nth(index).evaluate(  # noqa: SLF001
            """(el) => {
                const rect = el.closest('ruby').getBoundingClientRect();
                return {y: rect.y, height: rect.height};
            }"""
        )
        # The annotation must start above the vertical middle of its ruby box.
        if annotation.y >= base["y"] + base["height"] / 2:
            misaligned.append(
                (index, round(annotation.y, 1), round(base["y"], 1), base["height"])
            )
    assert not misaligned, (
        "rt annotations are not rendered above their ruby base "
        f"(index, rt_y, ruby_y, ruby_height): {misaligned}"
    )


def test_ruby_annotation_is_smaller_than_its_base(renderer, card, styles_css):
    """Furigana must read as annotation, not compete with the sentence."""
    rendered = renderer.render(card("ruby_furigana"), styles_css=styles_css)
    rendered.open_details(sel.EXAMPLES)
    rt_size = float(rendered.computed("rt", "font-size").removesuffix("px"))
    base_size = float(rendered.computed(sel.EXAMPLE_JA, "font-size").removesuffix("px"))
    assert rt_size < base_size, (
        f"furigana font-size {rt_size}px is not smaller than the example text "
        f"{base_size}px"
    )


def test_expanded_examples_do_not_overlap_each_other(renderer, card, styles_css):
    """Example items stack; they never share pixels."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    rendered.open_details(sel.EXAMPLES)
    boxes = rendered.boxes(sel.EXAMPLE)
    overlaps = [
        (index, boxes[index], boxes[index + 1])
        for index in range(len(boxes) - 1)
        if boxes[index].overlaps(boxes[index + 1])
    ]
    assert not overlaps, f"adjacent example items overlap: {overlaps[:3]}"


def test_headword_row_stays_on_one_line_on_desktop(renderer, card, styles_css):
    """The compact block is compact: headword and badges share a line."""
    rendered = renderer.render(card("english_gloss"), styles_css=styles_css)
    expression = rendered.box(sel.EXPRESSION)
    badges = rendered.boxes(sel.JLPT)
    stray = [
        (index, round(box.y, 1))
        for index, box in enumerate(badges)
        if abs(box.y - expression.y) > expression.height
    ]
    assert not stray, (
        f"JLPT badge(s) wrapped off the headword line at desktop width "
        f"(expression y={expression.y}): {stray}"
    )
