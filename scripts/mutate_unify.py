"""Prove tests/test_unify.py bites: mutate the production path, expect a failure.

A green suite shows the merge works; it does not show a regression would be
caught. Each mutation below breaks one policy decision the module documents. A
surviving mutation is either a missing test or dead code.

Pristine bytes come from git, not from disk: an interrupted run leaves the file
mutated and the next run would faithfully "restore" the mutation.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = pathlib.Path("src/bugd/unify.py")
SUITE = "tests/test_unify.py"

#: (label, exact source to replace, replacement)
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "tolerate a row missing from the keymap (the silent-corpus-loss defect)",
        "    if unresolved:\n        raise StaleKeymap(unresolved, substantive)",
        "    if False:\n        raise StaleKeymap(unresolved, substantive)",
    ),
    (
        "sort senses lexicographically so #sense10 precedes #sense2",
        "        for canonical_key in sorted(by_key, key=natural_key):\n            point = keymap.points[canonical_key]\n            members = by_key[canonical_key]",
        "        for canonical_key in sorted(by_key):\n            point = keymap.points[canonical_key]\n            members = by_key[canonical_key]",
    ),
    (
        "make natural_key purely lexicographic",
        "    parts = _DIGITS.split(text)\n    return tuple(int(part) if part.isdigit() else part for part in parts)",
        "    return (text,)",
    ),
    (
        "de-duplicate examples globally instead of per source",
        "        scope = seen[contribution.source]",
        '        scope = seen["*"]',
    ),
    (
        "drop keep-last-when-emptied so a section can render blank",
        "        if not kept and not any(\n            getattr(contribution, name) for name in _SUBSTANCE_FIELDS\n        ):",
        "        if False:",
    ),
    (
        "stop counting removed duplicates",
        "        removed += dropped",
        "        removed += 0",
    ),
    (
        "reconcile conflicting JLPT levels to the first one",
        '                jlpt_levels=tuple(sorted(jlpt)),',
        '                jlpt_levels=tuple(sorted(jlpt))[:1],',
    ),
    (
        "stop emitting redirects, losing 745 lookups",
        "    redirects, redirect_stats = build_redirects(rows, entries, labels)\n    entries.extend(redirects)",
        "    redirects, redirect_stats = build_redirects(rows, entries, labels)\n    redirects = []",
    ),
    (
        "guess an ambiguous reading-mediated target instead of reporting it",
        "                if len(candidates) == 1:",
        "                if len(candidates) >= 1:",
    ),
    (
        "prefer the alphabetical expression over the bucket key as headword",
        "    if bucket_key in expressions:\n        return bucket_key",
        "    if False:\n        return bucket_key",
    ),
    (
        "fold the AI channel into human-authored meaning",
        '        ai_generated=_mapping(record.get("ai_generated"), "ai_generated"),\n        provenance=_mapping(record.get("provenance"), "provenance"),\n        duplicate_examples_removed=duplicate_examples_removed,',
        '        ai_generated={},\n        provenance=_mapping(record.get("provenance"), "provenance"),\n        duplicate_examples_removed=duplicate_examples_removed,',
    ),
    (
        "drop the AI flag on examples",
        "                ai_generated=bool(item.get(\"ai_generated\")),",
        "                ai_generated=False,",
    ),
    (
        "carry a redundant reading equal to the headword",
        "        if reading and reading != expression:\n            return reading",
        "        if reading:\n            return reading",
    ),
    (
        "let a point entry exist with no senses",
        '        if self.kind == KIND_POINT and not self.senses:\n            raise MalformedPayload(f"a {KIND_POINT} entry must carry at least one sense")',
        "        if False:\n            raise MalformedPayload(\"unreachable\")",
    ),
    (
        "accept any keymap schema version",
        "    if schema != SUPPORTED_KEYMAP_SCHEMA:",
        "    if False:",
    ),
    (
        "silently accept a dangling canonicalKey in the keymap",
        "    if unknown:\n        raise MalformedPayload(",
        "    if False:\n        raise MalformedPayload(",
    ),
    (
        "emit int-keyed histograms so stats and the written file disagree",
        "        return {str(key): counter[key] for key in sorted(counter)}",
        "        return {key: counter[key] for key in sorted(counter)}",
    ),
)


def pristine() -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{TARGET}"], cwd=REPO, capture_output=True, text=True
    )
    if out.returncode == 0:
        return out.stdout
    # Not yet committed on this branch: fall back to the index, then disk.
    for args in (["git", "show", f":{TARGET}"],):
        out = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout
    return (REPO / TARGET).read_text(encoding="utf-8")


def failed_tests(stdout: str) -> list[str]:
    """Only FAILED lines attribute a kill; substring matching invents them."""
    return re.findall(r"^FAILED (\S+)", stdout, flags=re.MULTILINE)


def main() -> int:
    original = pristine()
    path = REPO / TARGET
    survived: list[str] = []
    skipped: list[str] = []

    try:
        for label, old, new in MUTATIONS:
            if original.count(old) != 1:
                skipped.append(f"{label} (anchor matched {original.count(old)}x)")
                print(f"SKIP      {label}  <-- anchor is not unique/present")
                continue
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", SUITE, "-q", "-x", "--no-header"],
                cwd=REPO,
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "PYTHONPATH": "src"},
            )
            if result.returncode == 0:
                survived.append(label)
                print(f"SURVIVED  {label}")
            else:
                killers = failed_tests(result.stdout) or ["(collection/error)"]
                print(f"killed    {label}\n            by {killers[0]}")
    finally:
        path.write_text(original, encoding="utf-8")

    print()
    print(f"mutations: {len(MUTATIONS)}  killed: {len(MUTATIONS) - len(survived) - len(skipped)}"
          f"  survived: {len(survived)}  skipped: {len(skipped)}")
    for label in survived:
        print("  SURVIVING:", label)
    for label in skipped:
        print("  SKIPPED:", label)
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
