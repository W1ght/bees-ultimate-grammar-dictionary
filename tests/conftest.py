"""Shared test fixtures for the pipeline skeleton."""

from __future__ import annotations

import hashlib
import pathlib
import re

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
