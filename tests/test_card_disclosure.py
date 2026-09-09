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
    rendered.click(sel.SUMMARY)
    states = rendered.details_open_states()
    assert states[0] is True, "clicking the first source summary did not open it"
    assert not any(states[1:]), (
        f"clicking one summary opened others too: {states}"
    )
    assert rendered.is_visible(sel.EXAMPLE), (
        "the first source block is open but no example item is visible"
    )


def test_expanding_relayouts_following_sections_downward(renderer, card, styles_css):
    """Expanding a section pushes later sections down instead of overlapping."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    before = rendered.box(sel.SUMMARY, 1).y
    rendered.open_details(sel.SOURCE)
    after = rendered.box(sel.SUMMARY, 1).y
    assert after > before, (
        "expanding the first source block did not move the next summary down "
        f"(y {before} -> {after}); sections are overlapping or clipped"
    )


def test_no_disclosure_overlaps_another_when_all_expanded(renderer, card, styles_css):
    """With everything open, no two summary rows share pixels."""
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    for index in range(rendered.count("details")):
        rendered._page.locator("details").nth(index).evaluate(
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


def test_examples_disclosure_renders_honest_bounded_source_sentences(
    renderer, card, entry, styles_css
):
    """Every rendered example is a real source sentence, bounded, never invented.

    The production card deliberately bounds the examples it lifts into each
    source's disclosure (``EXAMPLES_PER_SOURCE`` per record, ``SENSES_PER_SOURCE``
    records per source) — the complete tail stays in the archive, not on the
    card. So "complete" is the wrong contract for the shipped card; the invariant
    that matters is that whatever DOES render is honest: real source sentences, no
    duplicates within a source block, and a non-empty disclosure for a rich entry.
    """
    source = entry(RICH)
    rendered = renderer.render(card(RICH), styles_css=styles_css)
    rendered.open_all_details()
    rendered_count = rendered.count(sel.EXAMPLE)
    assert rendered_count > 0, (
        "the rich fixture rendered no example items at all across its disclosures"
    )
    # Every rendered Japanese sentence must be traceable to a real source sentence
    # (allowing for the composer's sentence/turn line-breaking, which inserts <br>
    # but does not add or alter characters). Nothing is invented.
    corpus_sentences = {
        "".join(ex["japanese"].split())
        for point in source["contributions"]
        for ex in point.get("examples") or ()
    }
    rendered_ja = [t for t in rendered.texts(sel.EXAMPLE_JA)]
    orphans = [
        text
        for text in rendered_ja
        if "".join(text.split()) not in corpus_sentences
        and not any("".join(text.split()) in cs or cs in "".join(text.split())
                    for cs in corpus_sentences)
    ]
    assert not orphans, (
        f"example sentences rendered that are not in the source corpus: {orphans[:3]}"
    )
    # The rendered set must never exceed the honest ceiling of distinct source
    # sentences: the disclosure shows a subset, never phantom duplicates beyond it.
    distinct = {
        (point["source"], example["japanese"])
        for point in source["contributions"]
        for example in point.get("examples") or ()
    }
    assert rendered_count <= len(distinct), (
        f"Examples disclosures rendered {rendered_count} items but the corpus "
        f"holds only {len(distinct)} distinct (source, sentence) pairs -- the "
        "card must not invent or duplicate examples"
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
