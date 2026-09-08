"""Disclosure behaviour and keyboard access, in the real Yomitan renderer.

The card ships no JavaScript, so every claim here is about native
`details`/`summary` behaving as the contract assumes *inside* Yomitan's popup
cascade -- which is where a dictionary stylesheet or a host CSS rule could break
it without any test on the source JSON noticing.
"""

from __future__ import annotations

import pytest

from harness import selectors as sel
from harness.contract import MIN_TOUCH_TARGET_PX

RICH = "multi_source_rich"


def test_every_disclosure_starts_closed(renderer, card, styles_css):
    """Progressive disclosure: the lookup path is short by default."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    states = rendered.details_open_states()
    assert states, "the rich fixture rendered no <details> sections at all"
    assert not any(states), (
        f"{sum(states)} of {len(states)} disclosures start open; "
        f"summaries: {rendered.texts('summary')}"
    )


def test_disclosure_sections_follow_contract_order(renderer, card, styles_css):
    """Sections render in the frozen order, measured by y coordinate."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    order: list[tuple[str, float]] = []
    for section in sel.DISCLOSURE_SECTIONS:
        for index in range(rendered.count(section)):
            order.append((section, rendered.box(section, index).y))
    assert order == sorted(order, key=lambda pair: pair[1]), (
        "disclosure sections are out of contract order "
        f"{list(sel.DISCLOSURE_SECTIONS)}; measured (selector, top_px): {order}"
    )


def test_summary_click_expands_and_reveals_content(renderer, card, styles_css):
    """A real pointer click on the summary opens its own section only."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    assert not rendered.is_visible(sel.EXAMPLE), (
        "example items are visible while every disclosure is still closed"
    )
    rendered.click(f"{sel.EXAMPLES} > summary")
    states = rendered.details_open_states()
    assert states[0] is True, "clicking the Examples summary did not open it"
    assert not any(states[1:]), (
        f"clicking one summary opened others too: {states}"
    )
    assert rendered.is_visible(sel.EXAMPLE), (
        "Examples is open but no example item is visible"
    )


def test_expanding_relayouts_following_sections_downward(renderer, card, styles_css):
    """Expanding a section pushes later sections down instead of overlapping."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    before = rendered.box(sel.SUMMARY, 1).y
    rendered.open_details(sel.EXAMPLES)
    after = rendered.box(sel.SUMMARY, 1).y
    assert after > before, (
        "expanding Examples did not move the next summary down "
        f"(y {before} -> {after}); sections are overlapping or clipped"
    )


def test_no_disclosure_overlaps_another_when_all_expanded(renderer, card, styles_css):
    """With everything open, no two summary rows share pixels."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    for index in range(rendered.count("details")):
        rendered._page.locator("details").nth(index).evaluate(  # noqa: SLF001
            "el => el.open = true"
        )
    boxes = rendered.boxes(sel.SUMMARY)
    overlaps = [
        (i, i + 1, boxes[i], boxes[i + 1])
        for i in range(len(boxes) - 1)
        if boxes[i].overlaps(boxes[i + 1])
    ]
    assert not overlaps, f"summary rows overlap when fully expanded: {overlaps}"


def test_keyboard_tab_reaches_every_disclosure(renderer, card, styles_css):
    """Tab order includes every summary, in document order."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    expected = rendered.texts("summary")
    reached = [
        stop["text"] for stop in rendered.focus_order(limit=40) if stop["tag"] == "summary"
    ]
    missing = [text for text in expected if text[:60] not in reached]
    assert not missing, (
        f"{len(missing)} disclosure(s) unreachable by keyboard: {missing}; "
        f"tab order reached {reached}"
    )


def test_enter_on_focused_summary_toggles_it(renderer, card, styles_css):
    """Native keyboard activation works inside the popup cascade."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    rendered.focus_order(limit=1)
    assert rendered.details_open_states()[0] is False
    rendered.press("Enter")
    assert rendered.details_open_states()[0] is True, (
        "Enter on the focused summary did not open the disclosure"
    )
    rendered.press("Enter")
    assert rendered.details_open_states()[0] is False, (
        "Enter did not close the disclosure again"
    )


def test_summary_focus_is_visible(renderer, card, styles_css):
    """A keyboard user must be able to see where focus is (WCAG 2.4.7)."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    ring = rendered.focus_ring(sel.SUMMARY)
    assert ring["isActiveElement"], "summary did not accept focus"
    visible = (
        ring["outlineStyle"] not in ("none", "")
        and ring["outlineWidth"] not in ("0px", "")
    ) or ring["boxShadow"] not in ("none", "")
    assert visible, (
        "focused summary has no visible focus indicator: "
        f"outline={ring['outlineStyle']} {ring['outlineWidth']} "
        f"{ring['outlineColor']}, box-shadow={ring['boxShadow']}"
    )


@pytest.mark.parametrize("viewport_name", ["desktop", "narrow"])
def test_summary_meets_minimum_target_size(
    renderer, card, styles_css, viewport_name, viewport
):
    """Disclosure controls are large enough to hit (WCAG 2.5.8, 24x24 CSS px).

    Asserted twice: once on the rendered height, and once on the declared
    `min-height`. Height alone is a weak gate -- Yomitan's default line box happens
    to render 25px here, so a card that declared no minimum at all would pass by
    luck and then regress the moment a font or line-height changed. The declared
    floor is what actually guarantees the target.
    """
    rendered = renderer.render(
        card(RICH), styles_css=styles_css, viewport=viewport(viewport_name)
    )
    undersized = [
        (index, round(box.height, 2), rendered.texts("summary")[index])
        for index, box in enumerate(rendered.boxes(sel.SUMMARY))
        if box.height < MIN_TOUCH_TARGET_PX
    ]
    assert not undersized, (
        f"{viewport_name}: {len(undersized)} summary row(s) shorter than the "
        f"{MIN_TOUCH_TARGET_PX}px minimum target size "
        f"(index, height_px, text): {undersized}"
    )
    declared = rendered.computed(sel.SUMMARY, "min-height")
    assert declared.endswith("px"), (
        f"{viewport_name}: summary min-height is {declared!r}; the target size "
        "must be a declared floor, not an accident of the current line box"
    )
    assert float(declared.removesuffix("px")) >= MIN_TOUCH_TARGET_PX, (
        f"{viewport_name}: summary declares min-height {declared}, below the "
        f"{MIN_TOUCH_TARGET_PX}px minimum target size. The rendered rows may "
        "clear it today, but nothing guarantees they still will after a font, "
        "line-height, or zoom change."
    )


def test_examples_disclosure_is_complete_not_truncated(
    renderer, card, entry, styles_css
):
    """A disclosure advertised as complete contains every source example."""
    source = entry(RICH)
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    rendered.open_details(sel.EXAMPLES)
    summary_text = rendered.text(f"{sel.EXAMPLES} > summary")
    rendered_count = rendered.count(sel.EXAMPLE)
    assert str(rendered_count) in summary_text, (
        f"summary {summary_text!r} does not state the rendered example count "
        f"({rendered_count})"
    )
    # Duplicate sentences within one source are deliberately collapsed, so the
    # honest floor is the count of distinct (source, sentence) pairs.
    distinct = {
        (point["source"], example["japanese"])
        for point in source["contributions"]
        for example in point.get("examples") or ()
    }
    assert rendered_count == len(distinct), (
        f"Examples disclosure rendered {rendered_count} items but the corpus "
        f"holds {len(distinct)} distinct (source, sentence) pairs -- a "
        "'complete' disclosure must not be truncated to a card budget"
    )


def test_every_contributing_source_is_attributed(
    renderer, card, entry, styles_css, source_labels
):
    """No rendered statement is unattributed: each source is visibly labelled."""
    source = entry(RICH)
    contributing = sorted({point["source"] for point in source["contributions"]})
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    visible = " ".join(rendered.texts("summary"))
    rendered.open_details(sel.SOURCES)
    visible += " " + " ".join(rendered.texts(sel.SOURCE_LABEL))
    missing = [
        (name, source_labels[name])
        for name in contributing
        if source_labels[name] not in visible
    ]
    assert not missing, (
        f"contributing sources with no visible attribution (key, label): {missing}; "
        f"visible source labels were {rendered.texts(sel.SOURCE_LABEL)}"
    )
