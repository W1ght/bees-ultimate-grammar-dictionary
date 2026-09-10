"""The committed tree must be a runnable, reproducible repository.

UGD-16 convergence requirement: a fresh clone must contain every module the build
imports and every automation artifact that produced the shipped ZIP -- not just the
output data. Two real defects on this board motivated each test here:

* UGD-07/UGD-09 committed `keymap.py`/`banks.py` while leaving `axes.py`,
  `normalize.py`, `signature.py` and every source extractor UNTRACKED, so a clean
  clone failed `import bugd.keymap` with ModuleNotFoundError and the source registry
  loaded zero extractors. Every "green" suite passed only on untracked cruft in the
  main worktree.
* `.gitignore` excluded `/data/sources/*/` wholesale, which also excluded the
  `SOURCE.lock.json` digest manifests -- the reproducibility contract itself.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
import warnings

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def tracked() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


@pytest.fixture(scope="module")
def tracked_files() -> set[str]:
    files = tracked()
    if not files:
        pytest.skip("not a git checkout")
    return files


def test_every_relative_import_resolves_to_a_tracked_file(tracked_files: set[str]) -> None:
    """A tracked module may not import a file that is not itself tracked.

    Walks the committed graph rather than the working tree, because an untracked
    module sitting on disk satisfies a runtime import and hides the defect.
    """
    missing: list[str] = []
    for name in sorted(f for f in tracked_files if f.endswith(".py")):
        path = REPO / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = pathlib.Path(name).parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            base = package
            for _ in range(node.level - 1):
                base = base.parent
            parts = (node.module or "").split(".") if node.module else []
            target = base.joinpath(*parts) if parts else base
            candidates = {f"{target}.py", str(target / "__init__.py")}
            if candidates & tracked_files:
                continue
            # A namespace package (no __init__.py) is satisfied by any tracked
            # module inside it.
            if any(f.startswith(f"{target}/") for f in tracked_files):
                continue
            missing.append(f"{name} imports {'.' * node.level}{node.module or ''}")
    assert not missing, "tracked modules import untracked files:\n  " + "\n  ".join(missing)


def test_every_source_extractor_module_is_tracked(tracked_files: set[str]) -> None:
    """The registry populates itself by importing this package; all of it must ship.

    An untracked extractor does not raise -- it silently shrinks the dictionary,
    which is why this asserts the on-disk set equals the tracked set.
    """
    on_disk = {
        p.name
        for p in (REPO / "src" / "bugd" / "sources").glob("*.py")
        if not p.name.startswith("_")
    }
    committed = {
        pathlib.Path(f).name
        for f in tracked_files
        if f.startswith("src/bugd/sources/") and f.endswith(".py")
    }
    assert on_disk - committed == set(), f"untracked source modules: {sorted(on_disk - committed)}"


def test_the_source_lock_digest_manifests_are_tracked(tracked_files: set[str]) -> None:
    """`SOURCE.lock.json` is the reproducibility contract and must be committed.

    The locks pin every acquired byte by sha256 + byteCount + upstream URL, so an
    acquisition that drifts fails the build instead of silently building a
    different dictionary. They hold no source content, only hashes.
    """
    on_disk = sorted(
        str(p.relative_to(REPO)) for p in (REPO / "data" / "sources").glob("*/SOURCE.lock.json")
    )
    if not on_disk:
        pytest.skip("no acquired sources in this checkout")
    untracked = [p for p in on_disk if p not in tracked_files]
    assert not untracked, f"untracked SOURCE.lock.json manifests: {untracked}"


def test_no_acquired_source_payload_is_tracked(tracked_files: set[str]) -> None:
    """Only the manifests ship -- never the acquired bytes.

    The counterpart to the test above: relaxing .gitignore to admit the locks must
    not admit term banks, decks or archives. The acquired bytes are large and
    regenerable; the manifests that pin them are neither.
    """
    leaked = sorted(
        f
        for f in tracked_files
        if f.startswith("data/sources/")
        and not f.endswith("SOURCE.lock.json")
        and not f.endswith(".gitkeep")
    )
    assert not leaked, f"acquired source payload is tracked: {leaked}"


def test_every_tracked_lock_pins_every_file_by_digest() -> None:
    """A lock entry without a sha256 pins nothing, so it cannot detect drift."""
    locks = sorted((REPO / "data" / "sources").glob("*/SOURCE.lock.json"))
    if not locks:
        pytest.skip("no acquired sources in this checkout")
    for lock in locks:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        assert payload.get("files"), f"{lock} declares no files"
        for name, meta in payload["files"].items():
            assert isinstance(meta, dict), f"{lock}:{name} has no metadata"
            assert len(str(meta.get("sha256", ""))) == 64, f"{lock}:{name} has no sha256"


def test_every_third_party_import_in_src_is_a_declared_dependency(
    tracked_files: set[str],
) -> None:
    """A build dependency that only exists in someone's venv is not reproducible.

    `zstandard` shipped undeclared: `bugd.anki` imports it lazily inside
    `_zstd_decompress` and reports a missing module as an `AnkiPackageError` naming
    the member, which reads like a corrupt source rather than a missing dependency.
    Because it was installed in the main worktree's venv, `make extract` worked
    there and failed on a fresh `pip install -e .` with
    "collection.anki21b is zstd-compressed but the zstandard module is unavailable".
    Modern Anki exports zstd-compress the collection, so it is required by every
    `.apkg` source, not optional.

    Asserts the direction that matters: nothing imported may be undeclared. An
    unused declaration is waste, not a reproducibility defect.
    """
    import sys
    import tomllib

    declared = {
        re.split(r"[=<>!~\[]", spec, maxsplit=1)[0].strip().lower().replace("-", "_")
        for spec in tomllib.loads(
            (REPO / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["dependencies"]
    }
    imported: set[str] = set()
    for name in sorted(f for f in tracked_files if f.startswith("src/") and f.endswith(".py")):
        path = REPO / name
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imported.add(node.module.split(".")[0])
    third_party = {
        module
        for module in imported
        if module not in sys.stdlib_module_names and module != "bugd"
    }
    undeclared = sorted(m for m in third_party if m.lower().replace("-", "_") not in declared)
    assert not undeclared, (
        f"src/ imports undeclared dependencies: {undeclared}. "
        f"A fresh `pip install -e .` will not install them, so the build is not "
        f"reproducible from a clean checkout."
    )


def test_no_tracked_module_carries_an_invalid_escape_sequence(tracked_files: set[str]) -> None:
    """An invalid escape in a non-raw string is a future SyntaxError, and can ship.

    `styles.py` holds the whole stylesheet in a plain triple-quoted string, so a
    stray backslash is interpreted by PYTHON before the CSS is ever emitted. An
    ASCII-art brace in the vertical-rhythm comment (`7.69px  \\`) was a line
    CONTINUATION: it silently joined two rows of the diagram into one in the
    shipped `styles.css`, and `\\ ` on the next row emitted a literal backslash.
    A DeprecationWarning today, a SyntaxError in a future Python.
    """
    offenders: list[str] = []
    for name in sorted(f for f in tracked_files if f.endswith(".py")):
        path = REPO / name
        if not path.is_file():
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ast.parse(path.read_text(encoding="utf-8"))
        for record in caught:
            if issubclass(record.category, (DeprecationWarning, SyntaxWarning)):
                offenders.append(f"{name}: {record.message}")
    assert not offenders, "invalid escape sequences in tracked modules:\n  " + "\n  ".join(offenders)


def test_the_shipped_stylesheet_contains_no_stray_backslash() -> None:
    """The emitted CSS is the artifact; assert it, not just the source module."""
    from bugd.styles import STYLES_CSS

    assert "\\" not in STYLES_CSS, "a backslash survived into the shipped styles.css"
    # A line continuation would have merged two comment rows, so also assert the
    # comment delimiters still balance.
    assert STYLES_CSS.count("/*") == STYLES_CSS.count("*/")
