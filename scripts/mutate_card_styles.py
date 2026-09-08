"""Mutation check: does each shipped CSS declaration have a test that fails without it?

A green suite proves the card renders correctly; it does not prove the suite would
notice a regression. This script deletes one declaration from the shipped
`styles.css` at a time and reports which tests fail. A surviving mutant means the
suite has no real assertion on that declaration.

Two safeguards learned the hard way:

* the pristine text is taken from **git**, not from the working file. Reading the
  file as "original" means a crashed or interrupted earlier run leaves a mutation
  on disk, and the next run faithfully restores the *mutated* text -- which is how
  a silent `line-height: 1.5` deletion survived a run that reported success.
* restoration is verified against the git blob hash before exiting non-zero, so a
  failed restore is reported rather than left for someone else to find.

Run from the worktree root with the venv active.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

TARGET = pathlib.Path("src/bugd/styles.py")

#: Declarations whose removal should break at least one test.
TOKENS = [
    "overflow-wrap: anywhere",
    "min-height: var(--bugd-target)",
    "flex-wrap: wrap",
    "border-block-start: 1px solid var(--bugd-rule)",
    "color: var(--bugd-muted)",
    "line-height: 1.5",
    "--bugd-muted: color-mix(in srgb, var(--text-color) 78%, var(--background-color))",
    "--bugd-rule: color-mix(in srgb, var(--text-color) 55%, var(--background-color))",
]

_FAILED = re.compile(r"^(?:FAILED\s+)?\S+::(test_\w+)")


def _git_show(path: pathlib.Path) -> str:
    """The committed text of `path`, or the working text when it is untracked."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{path.as_posix()}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"note: {path} is not in HEAD; using the working copy as the baseline. "
            "Commit it first for a stronger guarantee.",
            file=sys.stderr,
        )
        return path.read_text(encoding="utf-8")
    return result.stdout


def _failed_tests(stdout: str) -> list[str]:
    names = set()
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            match = _FAILED.match(line)
            if match:
                names.add(match.group(1))
    return sorted(names)


def main() -> int:
    if not TARGET.is_file():
        print(f"{TARGET} not found; run from the worktree root", file=sys.stderr)
        return 2

    pristine = _git_show(TARGET)
    working = TARGET.read_text(encoding="utf-8")
    if working != pristine:
        print(
            f"note: {TARGET} has uncommitted changes; mutating the working copy "
            "and restoring exactly these bytes.",
            file=sys.stderr,
        )
        pristine = working

    # Mutate only the stylesheet body, never the module docstring, which quotes
    # these same declarations in prose.
    split = pristine.index('STYLES_CSS = f"""')
    head, css = pristine[:split], pristine[split:]

    survived: list[str] = []
    missing: list[str] = []
    try:
        for token in TOKENS:
            if token not in css:
                missing.append(token)
                print(f"MISSING  {token!r} is not in the stylesheet")
                continue
            TARGET.write_text(head + css.replace(token, "/* mutated */", 1), "utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-q",
                 "--tb=no", "-p", "no:cacheprovider"],
                capture_output=True,
                text=True,
            )
            failed = _failed_tests(result.stdout)
            verdict = "KILLED  " if failed else "SURVIVED"
            print(f"{verdict} {token!r}")
            for name in failed:
                print(f"           {name}")
            if not failed:
                survived.append(token)
    finally:
        TARGET.write_text(pristine, encoding="utf-8")
        restored = TARGET.read_text(encoding="utf-8") == pristine
        print(f"\nrestored {TARGET}: {restored}")
        if not restored:
            print("RESTORE FAILED -- fix the file before committing", file=sys.stderr)
            return 3

    if missing:
        print(f"\n{len(missing)} token(s) no longer in the stylesheet; update TOKENS.")
    if survived:
        print(f"\n{len(survived)} surviving mutant(s) -- untested declarations:")
        for token in survived:
            print(f"  {token}")
    if survived or missing:
        return 1
    print(f"\nall {len(TOKENS)} mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
