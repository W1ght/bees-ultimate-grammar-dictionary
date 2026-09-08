"""Above-fold structure, in the real Yomitan renderer.

The card contract's first promise is that a lookup is *concise*: expression,
gloss, structure, and nothing else. These tests assert the rendered semantic
tree, not the source JSON, so a change in how Yomitan's generator handles a
node is caught here rather than in production.
"""

from __future__ import annotations

import itertools

import pytest
from harness import selectors as sel
from harness.contract import MIN_BADGE_GAP_PX


def test_card_root_renders(renderer, card, styles_css):
    """The card is ONE structured-content root, not several sibling surfaces."""
    rendered = renderer.render(card("multi_source_rich"), styles_css=styles_css)
    assert rendered.count(sel.ROOT) == 1, (
        f"expected exactly one card root {sel.ROOT}; "
        f"found {rendered.count(sel.ROOT)} (one canonical surface per point)"
    )
    assert rendered.count(sel.ABOVE_FOLD) == 1


@pytest.mark.parametrize(
    "name",
    ["multi_source_rich", "english_gloss", "ruby_furigana", "no_jlpt", "sparse_minimal"],
)
def test_above_fold_holds_only_contract_rows(renderer, card, styles_css, name):
    """Nothing but headword/gloss/structure is above the fold.

    The failure mode this guards is drift: an extra badge, count, or provenance
    line added above the fold because the data happened to be available.
    """
    rendered = renderer.render(card(name), styles_css=styles_css)
    roles = rendered._page.evaluate(
        """(aboveFold) => {
            const node = document.querySelector(aboveFold);
            return [...node.children].map(
                (el) => Object.keys(el.dataset).join(',') || el.tagName.toLowerCase()
            );
        }""",
        sel.ABOVE_FOLD,
    )
    allowed = {"scCardHeadword", "scCardGloss", "scCardStructure"}
    unexpected = [role for role in roles if role not in allowed]
    assert not unexpected, (
        f"{name}: unexpected above-fold rows {unexpected}; "
        f"contract allows only {sorted(allowed)}"
    )


def test_above_fold_row_order_is_top_to_bottom(renderer, card, styles_css):
    """Rows render in contract order, measured by their y coordinates."""
    rendered = renderer.render(card("multi_source_rich"), styles_css=styles_css)
    present = [row for row in sel.ABOVE_FOLD_ROWS if rendered.exists(row)]
    tops = [(row, rendered.box(row).y) for row in present]
    assert tops == sorted(tops, key=lambda pair: pair[1]), (
        "above-fold rows are not in contract order (headword, gloss, structure); "
        f"measured tops: {tops}"
    )


def test_above_fold_precedes_every_disclosure(renderer, card, styles_css):
    """Progressive disclosure means the compact block is genuinely first."""
    rendered = renderer.render(card("multi_source_rich"), styles_css=styles_css)
    fold = rendered.box(sel.ABOVE_FOLD)
    first_summary = rendered.box(sel.SUMMARY)
    assert fold.bottom <= first_summary.y + 0.5, (
        f"above-fold block bottom={fold.bottom}px overlaps the first disclosure "
        f"summary at y={first_summary.y}px"
    )


def test_expression_is_marked_japanese(renderer, card, styles_css):
    """`lang=\"ja\"` reaches the DOM, so font selection and TTS are correct."""
    rendered = renderer.render(card("multi_source_rich"), styles_css=styles_css)
    assert rendered.attribute(sel.EXPRESSION, "lang") == "ja"
    assert rendered.attribute(sel.GLOSS, "lang") in (None, "ja")


def test_jlpt_badges_are_visually_separated(renderer, card, styles_css):
    """Adjacent JLPT badges must not run together into one unreadable token.

    `ほど` carries all five levels. With no inline separation they render as the
    single string `N5N4N3N2N1`, which is measured here rather than eyeballed.
    """
    rendered = renderer.render(card("english_gloss"), styles_css=styles_css)
    badges = rendered.boxes(sel.JLPT)
    assert len(badges) >= 2, (
        "fixture no longer exercises multiple JLPT badges; "
        f"found {len(badges)} for a multi-level entry"
    )
    gaps = [
        (index, round(right.x - left.right, 2))
        for index, (left, right) in enumerate(itertools.pairwise(badges))
    ]
    too_tight = [pair for pair in gaps if pair[1] < MIN_BADGE_GAP_PX]
    assert not too_tight, (
        f"JLPT badges are not separated: {sel.JLPT} gaps (px) {gaps}; "
        f"required >= {MIN_BADGE_GAP_PX}px. Rendered text: "
        f"{rendered.text(sel.HEADWORD)!r}"
    )


def test_missing_data_omits_its_row_without_placeholder(
    renderer, card, entry, styles_css
):
    """A sparse point renders fewer rows, never invented filler."""
    rendered = renderer.render(card("sparse_minimal"), styles_css=styles_css)
    assert rendered.exists(sel.EXPRESSION)
    source = entry("sparse_minimal")
    has_structure = any(
        (point.get("structure") or "").strip() for point in source["contributions"]
    )
    if not has_structure:
        assert not rendered.exists(sel.STRUCTURE), (
            "structure row rendered for an entry whose sources supply none"
        )
    text = rendered.text(sel.ABOVE_FOLD)
    for placeholder in ("n/a", "N/A", "unknown", "—?", "null", "None", "TODO"):
        assert placeholder not in text, (
            f"placeholder {placeholder!r} rendered above the fold: {text!r}"
        )


def test_no_jlpt_entry_renders_no_badge(renderer, card, entry, styles_css):
    """No source level means no badge, not an empty chip."""
    source = entry("no_jlpt")
    assert not any(point.get("jlpt") for point in source["contributions"]), (
        "fixture 'no_jlpt' now carries a JLPT level; it no longer tests absence"
    )
    rendered = renderer.render(card("no_jlpt"), styles_css=styles_css)
    assert rendered.count(sel.JLPT) == 0, (
        f"{rendered.count(sel.JLPT)} JLPT badge(s) rendered for an entry with no "
        "source-assigned level"
    )
