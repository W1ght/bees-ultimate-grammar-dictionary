"""Geometry contract the card must satisfy in the real Yomitan popup.

Numbers, not adjectives. Every value here is a threshold a rendered measurement
is compared against, so a regression reports the selector and the two numbers
rather than "looks wrong".
"""

from __future__ import annotations

#: Minimum separation between adjacent inline chips in the headword row. Without
#: it, five JLPT badges render as the single unreadable run `N5N4N3N2N1`.
MIN_BADGE_GAP_PX = 2.0

#: Minimum height of a disclosure control. WCAG 2.2 SC 2.5.8 (Target Size,
#: Minimum, AA) requires 24x24 CSS px. `summary` rows are the card's only
#: interactive controls, so they are held to it.
MIN_TOUCH_TARGET_PX = 24.0

#: WCAG 2.1 SC 1.4.3 contrast for normal-size body text (AA).
MIN_BODY_CONTRAST = 4.5

#: WCAG 2.1 SC 1.4.11 for non-text boundaries such as the disclosure rules.
MIN_NONTEXT_CONTRAST = 3.0

#: Sub-pixel layout rounding is not an overflow defect.
OVERFLOW_TOLERANCE_PX = 0.5

#: Root font size emulating a 200% browser zoom / large-text user (WCAG 1.4.4).
ZOOMED_ROOT_FONT_PX = 32

__all__ = [
    "MIN_BADGE_GAP_PX",
    "MIN_BODY_CONTRAST",
    "MIN_NONTEXT_CONTRAST",
    "MIN_TOUCH_TARGET_PX",
    "OVERFLOW_TOLERANCE_PX",
    "ZOOMED_ROOT_FONT_PX",
]
