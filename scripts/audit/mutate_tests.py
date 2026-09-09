"""Prove the shipped row-identity regressions bite.

Mutate one production declaration at a time and require a NAMED test to fail.
A green suite shows the fix works; it does not show a regression would be caught.

Pristine source is taken from git, not from disk: an interrupted run would
otherwise leave a file mutated and the next run would faithfully "restore" the
mutation. Attribution parses only `FAILED` lines — substring matching on pytest
output manufactures false kills.

Usage: mutate_tests.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = os.environ.get("BUGD_PY", sys.executable)

#: (label, file, old, new, test that must fail)
MUTATIONS = [
    (
        "drop the extract-time uniqueness gate",
        "src/bugd/sources/base.py",
        "        if previous is not None:\n            raise DuplicateRowIdentity(source, uid, previous, index)",
        "        if previous is not None:\n            pass",
        "test_a_duplicate_row_identity_fails_the_extraction_closed",
    ),
    (
        # A no-op first draft of this mutation (`index if point.source_id else index`)
        # was semantically identical to the original and "survived" — that was a
        # probe defect, not an untested declaration. This version derives the
        # ordinal from the DISTINCT source_id, which is exactly the filed defect:
        # two rows sharing a source_id collapse onto one identity.
        "number identities by distinct source_id instead of by row",
        "src/bugd/sources/base.py",
        "    stamped: list[GrammarPoint] = []\n"
        "    seen: dict[str, int] = {}\n"
        "    for index, point in enumerate(points, start=1):\n"
        "        uid = point.row_uid or row_uid(source, index)",
        "    stamped: list[GrammarPoint] = []\n"
        "    seen: dict[str, int] = {}\n"
        "    by_source_id: dict[str, int] = {}\n"
        "    for index, point in enumerate(points, start=1):\n"
        "        by_source_id.setdefault(point.source_id, len(by_source_id) + 1)\n"
        "        uid = point.row_uid or row_uid(source, by_source_id[point.source_id])",
        "test_every_extracted_row_is_stamped_with_its_own_identity",
    ),
    (
        "renumber a pre-assigned identity",
        "src/bugd/sources/base.py",
        "        uid = point.row_uid or row_uid(source, index)",
        "        uid = row_uid(source, index)",
        "test_a_preassigned_identity_survives_a_round_trip",
    ),
    (
        "accept any uid grammar on GrammarPoint",
        "src/bugd/model.py",
        "        if self.row_uid and not row_uid_matches(self.row_uid, self.source):",
        "        if False:",
        "test_a_malformed_row_identity_is_refused",
    ),
    (
        "loosen the ordinal grammar to int()-style digits",
        "src/bugd/model.py",
        'ROW_UID_ORDINAL = re.compile(r"[1-9][0-9]*\\Z", re.ASCII)',
        'ROW_UID_ORDINAL = re.compile(r"\\S+\\Z")',
        "test_a_malformed_row_identity_is_refused",
    ),
    (
        "let the merge accept a row with no identity",
        "src/bugd/unify.py",
        "    if not isinstance(uid, str) or not row_uid_matches(uid, source):",
        "    if False:",
        "test_a_row_without_an_identity_fails_the_merge_closed",
    ),
    (
        "carry source_id as the claim handle instead of the row identity",
        "src/bugd/unify.py",
        "        row_uid=uid,",
        '        row_uid=f"{source}:1",',
        "test_two_rows_sharing_a_source_id_keep_distinct_claim_handles",
    ),
    (
        "drop rowUid from the serialised artifact",
        "src/bugd/unify.py",
        '        "rowUid": contribution.row_uid,',
        "",
        "test_row_identity_survives_the_artifact_round_trip",
    ),
    (
        "drop rowUid when reading the artifact back",
        "src/bugd/unify.py",
        '        row_uid=str(payload.get("rowUid") or ""),',
        '        row_uid="",',
        "test_row_identity_survives_the_artifact_round_trip",
    ),
    (
        "drop identity in the projection onto the bank input",
        "src/bugd/unify.py",
        "        row_uid=contribution.row_uid,\n        expression=expression,",
        "        expression=expression,",
        "test_the_projection_onto_the_bank_input_keeps_row_identity",
    ),
]


def pristine(relative):
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative}"], cwd=REPO, capture_output=True, text=True
    )
    if proc.returncode == 0:
        return proc.stdout
    # A file not yet committed on this branch: fall back to the working copy,
    # captured ONCE at process start so a mutation cannot leak between rounds.
    return _WORKING.setdefault(relative, (REPO / relative).read_text(encoding="utf-8"))


_WORKING = {}
for _label, _file, _old, _new, _test in MUTATIONS:
    pristine(_file)


def failed_tests(output):
    return {
        match.group(1)
        for line in output.splitlines()
        if line.startswith("FAILED")
        for match in [re.search(r"::([A-Za-z0-9_]+)", line)]
        if match
    }


def main():
    results = []
    for label, relative, old, new, expected in MUTATIONS:
        path = REPO / relative
        original = pristine(relative)
        if old not in original:
            results.append((False, label, f"anchor not found in {relative}"))
            print(f"SURVIVED {label}\n           anchor not found in {relative}")
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            proc = subprocess.run(
                [PY, "-m", "pytest", "-q", "-p", "no:randomly",
                 "tests/test_sources.py", "tests/test_unify.py"],
                cwd=REPO,
                capture_output=True,
                text=True,
                env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
            )
        finally:
            path.write_text(original, encoding="utf-8")
        failures = failed_tests(proc.stdout)
        if expected in failures:
            results.append((True, label, f"{expected} FAILED (+{len(failures) - 1} others)"))
            print(f"KILLED   {label}\n           {expected} failed"
                  f"{f' (plus {len(failures) - 1} more)' if len(failures) > 1 else ''}")
        elif failures:
            results.append((False, label, f"wrong tests failed: {sorted(failures)[:4]}"))
            print(f"SURVIVED {label}\n           the named test passed; "
                  f"these failed instead: {sorted(failures)[:4]}")
        else:
            results.append((False, label, "suite stayed green"))
            print(f"SURVIVED {label}\n           the suite stayed GREEN — dead code "
                  f"or an untested declaration")

    # The tree must be pristine again.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    print()
    kills = sum(1 for ok, _l, _d in results if ok)
    print(f"MUTATIONS KILLED: {kills}/{len(results)}")
    print(f"src/ restored: {'yes' if not dirty else 'NO -> ' + dirty}")
    print("VERDICT:", "PASS" if kills == len(results) and not dirty else "FAIL")
    return 0 if kills == len(results) and not dirty else 1


if __name__ == "__main__":
    sys.exit(main())
