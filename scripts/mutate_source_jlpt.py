"""Prove the UGD-08b per-source JLPT tests bite: mutate, expect a failure.

A green suite shows the level renders; it does not show a regression would be
caught. Each mutation below breaks exactly one decision this change documents,
across both files it touched (`banks.py` and `styles.py`). A surviving mutation is
either a missing test or dead code.

Pristine bytes come from git, not from disk: an interrupted run leaves a file
mutated and the next run would faithfully "restore" the mutation.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SUITE = "tests/test_banks_card.py"

BANKS = pathlib.Path("src/bugd/banks.py")
STYLES = pathlib.Path("src/bugd/styles.py")

#: (target, label, exact source to replace, replacement)
MUTATIONS: tuple[tuple[pathlib.Path, str, str, str], ...] = (
    (
        BANKS,
        "stop emitting the per-source level (the original defect)",
        "        level_block = _source_level_block(levels)\n        if level_block is not None:\n            body.append(level_block)",
        "        level_block = None\n        if level_block is not None:\n            body.append(level_block)",
    ),
    (
        BANKS,
        "keep only the FIRST level a source asserts (reconcile by position)",
        "    levels: list[str] = []\n    for point in points:\n        if point.jlpt and point.jlpt not in levels:\n            levels.append(point.jlpt)\n    return levels",
        "    levels: list[str] = []\n    for point in points:\n        if point.jlpt and point.jlpt not in levels:\n            levels.append(point.jlpt)\n    return levels[:1]",
    ),
    (
        BANKS,
        "emit a level per SENSE, so one source repeats it up to 4x",
        "        if point.jlpt and point.jlpt not in levels:\n            levels.append(point.jlpt)",
        "        if point.jlpt:\n            levels.append(point.jlpt)",
    ),
    (
        BANKS,
        "refuse a disclosure to a source that asserts only a level (7 conflicts collapse)",
        "        levels = _source_levels(points)\n        if not rendered and not levels:",
        "        levels = _source_levels(points)\n        if not rendered:",
    ),
    (
        BANKS,
        "drop the 'JLPT' lead-in, leaving a bare ambiguous code in prose",
        '    body: list[object] = ["JLPT "]',
        '    body: list[object] = [""]',
    ),
    (
        BANKS,
        "drop the jlpt role from the per-source level, making it unstyled text",
        '            body.append(" · ")\n        body.append(_span("jlpt", level))',
        '            body.append(" · ")\n        body.append(level)',
    ),
    (
        BANKS,
        "let the level replace the compact badge instead of supplementing it",
        "        if not jlpt and point.jlpt:\n            jlpt = point.jlpt",
        "        if False:\n            jlpt = point.jlpt",
    ),
    (
        BANKS,
        "reorder the disclosure body so the level displaces the first sense",
        "        level_block = _source_level_block(levels)\n        if level_block is not None:\n            body.append(level_block)\n        for ordinal, (point, sense_body) in enumerate(shown, start=1):",
        "        level_block = _source_level_block(levels)\n        for ordinal, (point, sense_body) in enumerate(shown, start=1):",
    ),
    (
        BANKS,
        "truncate a source's senses by one while emitting the level",
        "        shown = rendered[:SENSES_PER_SOURCE]",
        "        shown = rendered[:SENSES_PER_SOURCE - 1]",
    ),
    (
        STYLES,
        "set the provenance row at body size, competing with the explanation",
        "[data-sc-source-level] {\n  margin-bottom: var(--bugd-space-tight);\n  font-size: 0.86em;",
        "[data-sc-source-level] {\n  margin-bottom: var(--bugd-space-tight);\n  font-size: 1.0em;",
    ),
    (
        STYLES,
        "draw the provenance row in primary text colour",
        "  font-size: 0.86em;\n  color: var(--bugd-muted);\n}",
        "  font-size: 0.86em;\n  color: var(--text-color, inherit);\n}",
    ),
    (
        STYLES,
        "delete the per-source level rule entirely",
        "[data-sc-source-level] {\n  margin-bottom: var(--bugd-space-tight);\n  font-size: 0.86em;\n  color: var(--bugd-muted);\n}",
        "[data-sc-source-level-unused] {\n  margin-bottom: var(--bugd-space-tight);\n  font-size: 0.86em;\n  color: var(--bugd-muted);\n}",
    ),
)


def pristine(target: pathlib.Path) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{target}"], cwd=REPO, capture_output=True, text=True
    )
    if out.returncode == 0:
        return out.stdout
    out = subprocess.run(
        ["git", "show", f":{target}"], cwd=REPO, capture_output=True, text=True
    )
    if out.returncode == 0:
        return out.stdout
    return (REPO / target).read_text(encoding="utf-8")


def failed_tests(stdout: str) -> list[str]:
    """Only FAILED lines attribute a kill; substring matching invents them."""
    return re.findall(r"^FAILED (\S+)", stdout, flags=re.MULTILINE)


def main() -> int:
    targets = {BANKS, STYLES}
    original = {target: pristine(target) for target in targets}
    survived: list[str] = []
    skipped: list[str] = []

    try:
        for target, label, old, new in MUTATIONS:
            source = original[target]
            if source.count(old) != 1:
                skipped.append(f"{label} (anchor matched {source.count(old)}x)")
                print(f"SKIP      {label}  <-- anchor is not unique/present")
                continue
            (REPO / target).write_text(source.replace(old, new, 1), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", SUITE, "-q", "-x", "--no-header"],
                cwd=REPO,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": "src"},
            )
            (REPO / target).write_text(source, encoding="utf-8")
            if result.returncode == 0:
                survived.append(label)
                print(f"SURVIVED  {label}")
            else:
                killers = failed_tests(result.stdout) or ["(collection/error)"]
                print(f"killed    {label}\n            by {killers[0]}")
    finally:
        for target in targets:
            (REPO / target).write_text(original[target], encoding="utf-8")

    print()
    killed = len(MUTATIONS) - len(survived) - len(skipped)
    print(
        f"mutations: {len(MUTATIONS)}  killed: {killed}"
        f"  survived: {len(survived)}  skipped: {len(skipped)}"
    )
    for label in survived:
        print("  SURVIVING:", label)
    for label in skipped:
        print("  SKIPPED:", label)
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
