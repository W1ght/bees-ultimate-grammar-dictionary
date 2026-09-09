"""Shared test fixtures for the pipeline skeleton."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bugd.model import Example, GrammarPoint

#: Committed/derived artifacts a test must never write. A stage test that lets a
#: default output path through does not fail -- it silently overwrites the real
#: artifact, and the next audit reports a corpus of zero. This happened: the
#: `all` CLI stage ran with an empty extracted dir but the DEFAULT unified path
#: and truncated `data/merge/unified.jsonl` to 0 bytes, which then presented as
#: "the packaged bank has 2,441 entries but the dataset has 0".
_GUARDED_ARTIFACTS = (
    "data/merge/unified.jsonl",
    "data/merge/unified.stats.json",
    "data/merge/keymap.json",
    "data/merged/corpus.json",
)

_REPO = pathlib.Path(__file__).resolve().parents[1]


def _fingerprint() -> dict[str, str | None]:
    prints: dict[str, str | None] = {}
    for name in _GUARDED_ARTIFACTS:
        path = _REPO / name
        prints[name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return prints


@pytest.fixture(autouse=True, scope="session")
def _repository_artifacts_are_read_only():
    """Fail the run if the suite mutated a repository artifact.

    Session-scoped so it costs four hashes per run, and asserted at teardown so
    the failure names the artifact rather than surfacing as a mystified audit.
    """
    before = _fingerprint()
    yield
    after = _fingerprint()
    changed = sorted(name for name in before if before[name] != after[name])
    assert not changed, (
        "the test suite wrote repository artifacts: "
        + ", ".join(changed)
        + ". Redirect every stage output under tmp_path (--unified/--keymap/"
        "--merged-dir or the run_* keyword arguments)."
    )


def resolve_space_tokens(css: str) -> str:
    """Substitute the card's `--bugd-space-*` scale into a CSS string.

    The vertical rhythm moved from seven ad-hoc literal lengths to one four-step
    scale declared on `[data-sc-grammar-card]`. Existing tests assert real
    numbers by regex (`margin-top:\\s*([0-9.]+)em`), which is the right shape --
    a threshold test that only checked for the token NAME could not tell 0.2em
    from 2em and would stop biting.

    So resolve the tokens to their declared values first and keep asserting
    numbers. A token with no declaration is left as-is, which makes the assertion
    fail loudly rather than silently pass on an unresolvable value.
    """
    decls = dict(
        re.findall(r"(--bugd-space-[a-z]+):\s*([0-9.]+em)\s*;", css)
    )
    if not decls:  # pragma: no cover - guards a rename of the scale
        raise AssertionError("no --bugd-space-* scale found in the stylesheet")

    def sub(match: re.Match[str]) -> str:
        return decls.get(match.group(1), match.group(0))

    return re.sub(r"var\((--bugd-space-[a-z]+)\)", sub, css)


@pytest.fixture
def sample_point() -> GrammarPoint:
    return GrammarPoint(
        source="fixture",
        source_id="1",
        # Row identity, as `ExtractResult` would stamp it. Set explicitly because
        # the merge stage fails closed on a row without one: `source_id` is not
        # unique, so a contribution built from an unstamped row would not be
        # traceable to a single source record.
        row_uid="fixture:1",
        expression="そうです",
        variants=("そうだ",),
        meaning="hearsay; I hear that",
        structure="Verb[casual] + そうです",
        jlpt="N4",
        examples=(
            Example(
                japanese="雨が降るそうです。",
                english="I hear it will rain.",
                highlight=("そうです",),
            ),
        ),
        provenance={"notetype": "fixture"},
    )


# --- real-Yomitan render suite (UGD-12) ---------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from harness.card_builder import build_card
from harness.yomitan_harness import (
    EXPECTED_YOMITAN_VERSION,
    YomitanRenderer,
    serve_yomitan,
    yomitan_revision,
)

FIXTURE_CORPUS = Path(__file__).parent / "harness" / "fixture_corpus.json"

#: Set when the pinned Yomitan checkout or a browser is unavailable, so the
#: render suite skips loudly instead of silently reporting a green run.
_SKIP = "real-Yomitan render suite unavailable: "


@pytest.fixture(scope="session")
def fixture_corpus() -> dict[str, Any]:
    """Representative entries taken verbatim from the real merged corpus."""
    with FIXTURE_CORPUS.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def source_labels(fixture_corpus: dict[str, Any]) -> dict[str, str]:
    return fixture_corpus["sourceLabels"]


@pytest.fixture(scope="session")
def styles_css() -> str:
    """The dictionary's shipped `styles.css`, as the packager emits it."""
    from bugd.styles import STYLES_CSS

    return STYLES_CSS


@pytest.fixture(scope="session")
def yomitan_url() -> Iterator[str]:
    try:
        revision = yomitan_revision()
    except Exception as error:  # noqa: BLE001 - environment guard, skips loudly
        pytest.skip(f"{_SKIP}{error}")
    if not revision["describe"].startswith(EXPECTED_YOMITAN_VERSION):
        pytest.fail(
            "harness is rendering the wrong Yomitan: expected "
            f"{EXPECTED_YOMITAN_VERSION}, checkout describes as "
            f"{revision['describe']!r} ({revision['commit'][:12]})"
        )
    if revision["dirty"]:
        pytest.fail(
            "pinned Yomitan checkout has uncommitted changes to tracked files; "
            "geometry measured against it is not reproducible:\n"
            f"{revision['dirty']}"
        )
    with serve_yomitan() as url:
        yield url


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - environment guard
        pytest.skip(f"{_SKIP}playwright is not installed")
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as error:  # noqa: BLE001 - environment guard, skips loudly
            pytest.skip(f"{_SKIP}{error}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def renderer(browser: Any, yomitan_url: str) -> Iterator[YomitanRenderer]:
    """A fresh page, with any JS error in the real generator failing the test."""
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None
        ),
    )
    requests: list[str] = []
    page.on(
        "request",
        lambda request: requests.append(request.url),
    )
    render = YomitanRenderer(page, yomitan_url)
    render.errors = errors  # type: ignore[attr-defined]
    render.requests = requests  # type: ignore[attr-defined]
    try:
        yield render
        assert not errors, f"real Yomitan raised while rendering the card: {errors}"
    finally:
        page.close()


@pytest.fixture
def card(fixture_corpus: dict[str, Any], source_labels: dict[str, str]):
    """`card(name)` -> structured content for one fixture corpus entry."""
    from harness.card_builder import unavailable_reason

    reason = unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    def build(name: str) -> Any:
        try:
            entry = fixture_corpus["entries"][name]
        except KeyError:
            available = sorted(fixture_corpus["entries"])
            raise AssertionError(f"unknown fixture entry {name!r}; have {available}") from None
        return build_card(entry, source_labels)

    return build


@pytest.fixture
def entry(fixture_corpus: dict[str, Any]):
    """`entry(name)` -> the raw merged-corpus record behind a fixture card."""
    return lambda name: fixture_corpus["entries"][name]


@pytest.fixture(scope="session")
def viewport():
    """`viewport("narrow")` -> the viewport dict for a named width.

    Named rather than inlined so a geometry failure message says `narrow` and
    every test measures the same two widths.
    """
    from harness.yomitan_harness import DESKTOP_VIEWPORT, NARROW_VIEWPORT

    sizes = {"desktop": DESKTOP_VIEWPORT, "narrow": NARROW_VIEWPORT}

    def resolve(name: str) -> dict[str, int]:
        try:
            return sizes[name]
        except KeyError:
            raise AssertionError(
                f"unknown viewport {name!r}; have {sorted(sizes)}"
            ) from None

    return resolve
