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
def test_card_fits_the_popup_when_a_section_is_expanded(
    renderer, card, styles_css, viewport, viewport_name
):
    """Expanding a disclosure must not widen the card past the popup.

    The production card discloses one native ``details`` per contributing source;
    each is opened in turn (long producer prose, construction tables, and example
    sentences are the content that historically broke this — unbreakable Japanese
    runs and long tokens that set the width of every ancestor up to the card root).
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport(viewport_name)
    )
    count = rendered.count(sel.SOURCE)
    assert count > 0, "rich fixture rendered no source disclosures"
    for index in range(count):
        rendered._page.locator(sel.SOURCE).nth(index).evaluate("el => el.open = true")
        _assert_contained(
            rendered, f"{RICH} @ {viewport_name}, source block {index} expanded"
        )


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


def test_long_unbreakable_runs_wrap_rather_than_extend(renderer, card, styles_css, viewport):
    """The specific mechanism: long unbreakable content must be breakable.

    The production card renders no producer-URL anchors (each source's disclosure
    is titled by its name; the source IS the attribution), so the long-token
    stress falls on the roles that DO carry unbreakable runs: Japanese example
    sentences, source prose, and the construction badge. Asserted as a property of
    those rendered elements (they must be allowed to wrap and must not be clipped),
    not only as an absence of overflow, so the fix cannot be a clip that hides the
    tail of a long run.
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport("narrow")
    )
    rendered.open_all_details()
    # The width a run must fit inside is the popup's own frame. Yomitan wraps
    # every structured-content card in a `span.structured-content` whose
    # `display: inline` collapses the card root's border box to 0 in this
    # harness (the real popup stretches it via a flex content-body the bare
    # harness page has no equivalent of), so the root box is not a usable
    # width bound -- the frame is, and it is exactly the surface the whole-card
    # overflow report below measures against.
    frame_width = rendered.frame_box().width
    breakable_roles = [sel.EXAMPLE_JA, sel.EXPLANATION, sel.STRUCTURE]
    checked = 0
    for role in breakable_roles:
        if not rendered.exists(role):
            continue
        checked += 1
        widths = [round(box.width, 1) for box in rendered.boxes(role)]
        too_wide = [w for w in widths if w > frame_width + OVERFLOW_TOLERANCE_PX]
        wrap = rendered.computed(role, "overflow-wrap")
        white_space = rendered.computed(role, "white-space")
        overflow = rendered.computed(role, "overflow")
        assert not too_wide, (
            f"{role} runs are wider than the popup frame ({frame_width}px): "
            f"{too_wide}; overflow-wrap={wrap!r} white-space={white_space!r}. "
            "A long run must wrap, not extend the card."
        )
        assert overflow in ("visible", ""), (
            f"{role} is contained by clipping (overflow={overflow!r}), which "
            "hides content instead of wrapping it"
        )
    assert checked >= 2, (
        "the rich fixture no longer exercises the breakable long-run roles "
        f"{breakable_roles}"
    )
    _assert_contained(rendered, f"{RICH} @ narrow, fully expanded (long-run wrap)")


def test_furigana_ruby_sits_above_its_base_text(renderer, card, styles_css):
    """Ruby annotations must align over their base, not inline beside it."""
    rendered = renderer.render(card("ruby_furigana"), styles_css=styles_css)
    rendered.open_all_details()
    assert rendered.count("ruby") > 0, "ruby fixture rendered no <ruby> element"
    assert rendered.count("rt") > 0, "ruby fixture rendered no <rt> annotation"
    misaligned = []
    for index in range(rendered.count("rt")):
        annotation = rendered.box("rt", index)
        base = rendered._page.locator("rt").nth(index).evaluate(
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
    rendered.open_all_details()
    rt_size = float(rendered.computed("rt", "font-size").removesuffix("px"))
    base_size = float(rendered.computed(sel.EXAMPLE_JA, "font-size").removesuffix("px"))
    assert rt_size < base_size, (
        f"furigana font-size {rt_size}px is not smaller than the example text "
        f"{base_size}px"
    )


def test_expanded_examples_do_not_overlap_each_other(renderer, card, styles_css):
    """Example items stack; they never share pixels."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    rendered.open_all_details()
    boxes = rendered.boxes(sel.EXAMPLE)
    overlaps = [
        (index, boxes[index], boxes[index + 1])
        for index in range(len(boxes) - 1)
        if boxes[index].overlaps(boxes[index + 1])
    ]
    assert not overlaps, f"adjacent example items overlap: {overlaps[:3]}"


def test_metadata_row_stays_on_one_line_on_desktop(renderer, card, styles_css):
    """The compact block is compact: the metadata chips share one line.

    The production card sets the gloss on its own line and the construction badge
    and JLPT chip on a single metadata row beneath it. At desktop width that row
    must not wrap — the badge and the level sit side by side, not stacked.
    """
    rendered = renderer.render(card("english_gloss"), styles_css=styles_css)
    structure = rendered.box(sel.STRUCTURE)
    badges = rendered.boxes(f"{sel.METAROW} {sel.JLPT}")
    assert badges, "english_gloss rendered no JLPT badge on the metadata row"
    stray = [
        (index, round(box.y, 1))
        for index, box in enumerate(badges)
        if abs(box.y - structure.y) > structure.height
    ]
    assert not stray, (
        f"JLPT badge(s) wrapped off the metadata row at desktop width "
        f"(structure y={structure.y}): {stray}"
    )
