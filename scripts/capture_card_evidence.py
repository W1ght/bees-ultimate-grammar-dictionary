"""Capture real-Yomitan screenshots of the card for human review.

Not a test: the suite asserts geometry numerically. This exists so a person can
look at what those numbers describe, and so a beauty/QA reviewer downstream has
artifacts bound to a known revision rather than a re-render.

Usage (venv active, from the worktree root):
    python scripts/capture_card_evidence.py [output_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from harness import selectors as sel
from harness.card_builder import active_builder, build_card
from harness.yomitan_harness import (
    DESKTOP_VIEWPORT,
    NARROW_VIEWPORT,
    YomitanRenderer,
    serve_yomitan,
    yomitan_revision,
)

#: (name, fixture, render kwargs, sections to expand before the shot)
SHOTS = (
    ("desktop-collapsed", "multi_source_rich", {}, ()),
    ("desktop-expanded", "multi_source_rich", {}, (sel.EXAMPLES, sel.SOURCES)),
    ("narrow-collapsed", "multi_source_rich", {"viewport": NARROW_VIEWPORT}, ()),
    (
        "narrow-sources-expanded",
        "multi_source_rich",
        {"viewport": NARROW_VIEWPORT},
        (sel.SOURCES,),
    ),
    ("dark-collapsed", "multi_source_rich", {"theme": "dark"}, ()),
    (
        "dark-on-light-os",
        "multi_source_rich",
        {"theme": "dark", "os_scheme": "light"},
        (sel.SOURCES,),
    ),
    ("forced-colors", "multi_source_rich", {"forced_colors": True}, (sel.EXAMPLES,)),
    (
        "narrow-zoom-200",
        "multi_source_rich",
        {"viewport": NARROW_VIEWPORT, "font_size": 32},
        (),
    ),
    ("all-jlpt-badges", "english_gloss", {}, ()),
    ("ruby-furigana", "ruby_furigana", {}, (sel.EXAMPLES,)),
    ("sparse-entry", "sparse_minimal", {}, ()),
    (
        "most-variants",
        "most_variants",
        {"viewport": NARROW_VIEWPORT},
        (sel.ALSO_WRITTEN,),
    ),
)


def main() -> int:
    from playwright.sync_api import sync_playwright

    from bugd.styles import STYLES_CSS

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "evidence"
    out.mkdir(parents=True, exist_ok=True)

    corpus = json.loads(
        (ROOT / "tests" / "harness" / "fixture_corpus.json").read_text("utf-8")
    )
    labels = corpus["sourceLabels"]
    revision = yomitan_revision()

    manifest: dict[str, Any] = {
        "yomitan": revision,
        "cardBuilder": active_builder(),
        "viewports": {"desktop": DESKTOP_VIEWPORT, "narrow": NARROW_VIEWPORT},
        "shots": [],
    }
    shots: list[dict[str, Any]] = manifest["shots"]

    with serve_yomitan() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        renderer = YomitanRenderer(page, url)

        for name, fixture, kwargs, expand in SHOTS:
            card = build_card(corpus["entries"][fixture], labels)
            rendered = renderer.render(card, styles_css=STYLES_CSS, **kwargs)
            for section in expand:
                if rendered.exists(section):
                    rendered.open_details(section)
            path = rendered.screenshot(out / f"card-{name}.png")
            overflow = rendered.overflow_report()
            manifest_entry = {
                "name": name,
                "fixture": fixture,
                "options": {
                    key: value for key, value in kwargs.items() if key != "viewport"
                },
                "viewport": kwargs.get("viewport", DESKTOP_VIEWPORT),
                "expanded": list(expand),
                "file": path.name,
                "cardBox": rendered.box(sel.ROOT).__dict__,
                "overflowBoxes": len(overflow),
            }
            shots.append(manifest_entry)
            print(f"{path}  overflow_boxes={len(overflow)}")

        browser.close()

    if errors:
        print(f"\nJS errors during capture: {errors}", file=sys.stderr)
        return 1

    (out / "card-evidence.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(f"\nmanifest: {out / 'card-evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
