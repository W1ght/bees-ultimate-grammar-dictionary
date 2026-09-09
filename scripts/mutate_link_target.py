"""UGD-16: mutate the _link_target fix and confirm the new tests kill each mutant.

A green run shows the fold works; it does not show a regression would be caught.
Each mutation reverts one clause of the new rule and must produce a FAILED line
naming the test that owns that clause.

Pristine source is taken from git, never from disk, so an interrupted run cannot
"restore" a mutation.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

TARGET = pathlib.Path("src/bugd/keymap.py")
TESTS = "tests/test_keymap.py"

MUTATIONS = [
    (
        "restore the original ambiguous-target refusal",
        """    if len(others) == 1:
        (_, found), = others.items()
        return found[0] if len(found) == 1 else None""",
        """    if len(others) == 1:
        (_, found), = others.items()
        return found[0] if len(found) == 1 else None
    return None""",
        "test_a_reading_silent_source_does_not_block_an_orthographic_fold",
    ),
    (
        "accept a contradicting reading as if it were silence",
        "    if len(matching) != 1 or len(matching) + len(silent) != len(candidates):",
        "    if len(matching) != 1:",
        "test_a_contradicting_reading_still_refuses_the_fold",
    ),
    (
        "link to the first matching row instead of requiring a unique one",
        "    if len(matching) != 1 or len(matching) + len(silent) != len(candidates):",
        "    if len(matching) < 1 or len(matching) + len(silent) != len(candidates):",
        "test_two_rows_stating_the_same_reading_remain_ambiguous",
    ),
    (
        "drop the requirement that the proposer states a reading",
        """    if not row.reading_identity:
        return None
    candidates""",
        """    candidates""",
        "test_a_reading_silent_proposer_cannot_claim_a_multi_source_bucket",
    ),
]


def pristine() -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{TARGET}"], capture_output=True, text=True, check=True
    )
    return out.stdout


def failures(text: str) -> set[str]:
    return {
        m.group(1)
        for line in text.splitlines()
        if line.startswith("FAILED")
        for m in [re.search(r"::(\w+)", line)]
        if m
    }


def main() -> int:
    base = pristine()
    original_on_disk = TARGET.read_text(encoding="utf-8")
    if base != original_on_disk:
        print("NOTE: working tree differs from HEAD; mutating the HEAD bytes")
    killed = survived = 0
    try:
        for label, old, new, owner in MUTATIONS:
            if old not in base:
                print(f"PROBE DEFECT: anchor not found for {label!r}")
                survived += 1
                continue
            mutant = base.replace(old, new, 1)
            if mutant == base:
                print(f"PROBE DEFECT: mutation is a no-op for {label!r}")
                survived += 1
                continue
            TARGET.write_text(mutant, encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-m", "pytest", TESTS, "-q", "--no-header", "-p", "no:cacheprovider"],
                capture_output=True,
                text=True,
            )
            failed = failures(run.stdout + run.stderr)
            if owner is None:
                verdict = "KILLED" if failed else "SURVIVED"
                detail = f"(failed: {sorted(failed)[:3]})"
            elif owner in failed:
                verdict, detail = "KILLED", f"by {owner}"
            elif failed:
                verdict = "KILLED-BY-WRONG-TEST"
                detail = f"expected {owner}, got {sorted(failed)[:3]}"
            else:
                verdict, detail = "SURVIVED", "no test failed"
            if verdict == "KILLED":
                killed += 1
            else:
                survived += 1
            print(f"{verdict:22s} {label}  {detail}")
    finally:
        TARGET.write_text(base, encoding="utf-8")
        print(f"\nrestored {TARGET} from git")
    print(f"killed={killed} survived={survived}")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
