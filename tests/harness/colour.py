"""Colour helpers for theme legibility assertions.

WCAG contrast, computed from what the browser actually resolved, so a theme
regression that makes text illegible fails rather than being eyeballed.

Chromium does not always report a resolved colour as `rgb()`. A value produced by
`color-mix()` comes back in the modern CSS Color 4 form `color(srgb r g b)` with
channels in 0..1, and a value that inherits an alpha comes back as `rgba()`.
Parsing all of these is required: a parser that only understands `rgb()` reports
a *harness* failure for a perfectly legible colour, which reads as a card defect.
"""

from __future__ import annotations

import re

_LEGACY_RGB = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.%]+)\s*)?\)"
)

#: CSS Color 4 `color(<space> c1 c2 c3[ / alpha])`. Only sRGB-family spaces are
#: accepted: converting Lab/OKLab here would be guesswork, and a test asserting
#: contrast should say so rather than silently approximate.
_COLOR_FUNCTION = re.compile(
    r"color\(\s*(srgb|srgb-linear)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)"
    r"\s*(?:/\s*([\d.%]+)\s*)?\)"
)

#: System colour keywords forced-colors mode resolves to. A computed value that
#: is still a keyword means the browser did not resolve it, which is itself a
#: finding worth reporting rather than silently coercing to black.
SYSTEM_COLORS = {
    "canvas",
    "canvastext",
    "linktext",
    "visitedtext",
    "activetext",
    "buttonface",
    "buttontext",
    "highlight",
    "highlighttext",
    "graytext",
}


def _alpha(raw: str | None) -> float:
    if raw is None:
        return 1.0
    if raw.endswith("%"):
        return float(raw[:-1]) / 100.0
    return float(raw)


def parse_rgb(value: str) -> tuple[float, float, float, float]:
    """Any resolved sRGB colour -> (r, g, b, alpha) with r/g/b in 0..255.

    Accepts `rgb()`, `rgba()`, and CSS Color 4 `color(srgb ...)`. Raises on an
    unresolved keyword or a colour space this cannot convert exactly.
    """
    text = value or ""
    legacy = _LEGACY_RGB.search(text)
    if legacy is not None:
        r, g, b, alpha = legacy.groups()
        return float(r), float(g), float(b), _alpha(alpha)

    modern = _COLOR_FUNCTION.search(text)
    if modern is not None:
        space, r, g, b, alpha = modern.groups()
        channels = [float(r), float(g), float(b)]
        if space == "srgb-linear":
            # Re-encode to gamma sRGB so a single luminance path stays correct.
            channels = [
                value * 12.92
                if value <= 0.0031308
                else 1.055 * value ** (1 / 2.4) - 0.055
                for value in channels
            ]
        return (
            channels[0] * 255.0,
            channels[1] * 255.0,
            channels[2] * 255.0,
            _alpha(alpha),
        )

    raise AssertionError(
        f"expected a resolved sRGB colour, got {value!r}. A bare keyword means "
        "the browser did not resolve it; a non-sRGB color() space is not "
        "converted here because an approximate contrast number would be "
        "misleading."
    )


def _channel(value: float) -> float:
    srgb = value / 255.0
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    r, g, b, _ = parse_rgb(value)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def composite(foreground: str, background: str) -> str:
    """Flatten a translucent foreground over an opaque background."""
    fr, fg, fb, alpha = parse_rgb(foreground)
    br, bg, bb, _ = parse_rgb(background)
    return (
        f"rgb({fr * alpha + br * (1 - alpha)},"
        f"{fg * alpha + bg * (1 - alpha)},"
        f"{fb * alpha + bb * (1 - alpha)})"
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio, compositing alpha onto the background first."""
    flat = (
        composite(foreground, background)
        if parse_rgb(foreground)[3] < 1.0
        else foreground
    )
    light, dark = sorted((luminance(flat), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


__all__ = ["SYSTEM_COLORS", "composite", "contrast_ratio", "luminance", "parse_rgb"]
