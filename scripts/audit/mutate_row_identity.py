"""Mutate the row-identity fix and confirm every gate dies.

A passing probe proves nothing unless it can fail. Six mutations, each aimed at a
distinct claim the fix makes. All must be caught.

1. duplicate uid at extraction     -> `assign_row_uids` must raise
2. non-ASCII-digit ordinal         -> `GrammarPoint` must reject the uid
3. underscore-separated ordinal    -> `int()` accepts it, the grammar must not
4. uid prefixed with another source -> `GrammarPoint` must reject the uid
5. merge a row with no uid         -> `build_contribution` must fail closed
6. two contributions share one uid -> `row_identity.py` must report it
7. a uid repointed to another row  -> `row_identity.py` substance check must bite

Nothing here writes to the repository: every mutation is applied to an in-memory
copy or a temp file.

Usage: mutate_row_identity.py <unified.jsonl> <extracted-dir>
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))

from bugd.jsonio import MalformedPayload  # noqa: E402
from bugd.model import GrammarPoint  # noqa: E402
from bugd.sources.base import DuplicateRowIdentity, assign_row_uids  # noqa: E402
from bugd.unify import build_contribution  # noqa: E402


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()

results = []


def killed(name, detail):
    results.append((True, name, detail))
    print(f"KILLED   {name}\n           {detail}")


def survived(name, detail):
    results.append((False, name, detail))
    print(f"SURVIVED {name}\n           {detail}")


def probe(name, fn, expected):
    try:
        fn()
    except expected as error:
        killed(name, f"{type(error).__name__}: {str(error)[:150]}")
        return
    except Exception as error:  # noqa: BLE001
        survived(name, f"raised the WRONG error {type(error).__name__}: {error}")
        return
    survived(name, "no error raised")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unified", type=Path)
    parser.add_argument("extracted", type=Path)
    args = parser.parse_args()

    point = GrammarPoint(source="s", source_id="x", expression="あ")

    # 1. two rows claiming one uid must fail closed at extraction
    probe(
        "1 duplicate uid at extraction",
        lambda: assign_row_uids(
            "s",
            [
                GrammarPoint(source="s", source_id="a", expression="あ", row_uid="s:1"),
                GrammarPoint(source="s", source_id="b", expression="い", row_uid="s:1"),
            ],
        ),
        DuplicateRowIdentity,
    )

    # 2-4. uid grammar: Unicode digits, underscores and a foreign prefix are all
    # things `int()` or a naive startswith would wave through.
    for index, bad in enumerate(("s:１", "s:1_0", "other:1"), start=2):
        probe(
            f"{index} malformed uid {bad!r}",
            lambda bad=bad: GrammarPoint(
                source="s", source_id="x", expression="あ", row_uid=bad
            ),
            MalformedPayload,
        )

    # 5. merging a row that has no uid must fail closed rather than produce an
    #    unattributable contribution.
    probe(
        "5 merge a row with no row_uid",
        lambda: build_contribution(
            "s",
            {"source_id": "x", "expression": "あ", "examples": []},
            canonical_key="あ",
            source_label="S",
        ),
        MalformedPayload,
    )

    # 6-7. dataset-level probes: mutate a copy of unified.jsonl and re-run the
    #      independent row_identity gate on it.
    lines = args.unified.read_text(encoding="utf-8").splitlines()

    # Indexes the mutations need to build a mutation that is *only* wrong in the
    # way it claims to be.
    extracted = {}
    source_row_uids = collections.defaultdict(list)
    for path in sorted(args.extracted.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload["points"]:
            extracted[record["row_uid"]] = record
            source_row_uids[payload["source"]].append(record["row_uid"])
    claimed_uids = {
        c["rowUid"]
        for line in lines
        for entry in (json.loads(line),)
        if entry["kind"] == "point"
        for sense in entry["senses"]
        for c in sense["contributions"]
    }

    def run_gate(mutate, name, expect):
        """Apply one mutation and require the gate to fail on the NAMED check.

        `expect` is the exact `row_identity.py` failure label this mutation is
        supposed to trigger. Accepting any FAIL line would manufacture false
        kills: the first draft of mutation 6 copied a uid between contributions
        of two DIFFERENT sources, so it died as `malformed rowUid` (wrong prefix)
        rather than as the global-uniqueness violation it was written to test, and
        mutation 7's `+1` ordinal landed on a neighbour's uid and died as a
        duplicate instead of as a substance mismatch. Both looked like kills.
        """
        mutated = []
        applied = False
        for line in lines:
            entry = json.loads(line)
            if not applied and entry["kind"] == "point":
                applied = mutate(entry)
            mutated.append(json.dumps(entry, ensure_ascii=False))
        if not applied:
            survived(name, "the mutation could not be applied to the dataset")
            return
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unified.jsonl"
            path.write_text("\n".join(mutated) + "\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "row_identity.py"),
                    str(path),
                    str(args.extracted),
                    str(Path(tmp) / "out.json"),
                ],
                capture_output=True,
                text=True,
            )
        fails = [ln.strip() for ln in proc.stdout.splitlines() if ln.startswith("FAIL")]
        wanted = [ln for ln in fails if ln.startswith(f"FAIL {expect}:")]
        if proc.returncode == 0:
            survived(name, "gate exited 0")
        elif not wanted:
            survived(
                name,
                f"gate failed but NOT on {expect!r}; it reported {fails or ['nothing']}",
            )
        else:
            killed(name, wanted[0])

    def collide(entry):
        """Give two contributions OF ONE SOURCE the same uid.

        Same source on purpose: a cross-source copy would trip the prefix check
        first and never exercise global uniqueness.
        """
        by_source = collections.defaultdict(list)
        for sense in entry["senses"]:
            for c in sense["contributions"]:
                by_source[c["source"]].append(c)
        for members in by_source.values():
            if len(members) >= 2:
                members[1]["rowUid"] = members[0]["rowUid"]
                return True
        return False

    def repoint(entry):
        """Name a real but DIFFERENT row of the same source.

        The replacement uid must be well-formed, unclaimed anywhere else in the
        dataset, and belong to an extracted row whose substance differs — that is
        the only way to reach the substance check.
        """
        for sense in entry["senses"]:
            for c in sense["contributions"]:
                source = c["source"]
                for uid in source_row_uids[source]:
                    if uid in claimed_uids:
                        continue
                    if norm(extracted[uid].get("explanation")) == norm(c.get("explanation")):
                        continue
                    c["rowUid"] = uid
                    return True
        return False

    run_gate(collide, "6 two contributions of one source share a uid",
             "rowUid reused across the dataset")
    run_gate(repoint, "7 uid repointed to a different row of the same source",
             "rowUid names a row with different substance")

    print()
    kills = sum(1 for ok, _n, _d in results if ok)
    print(f"MUTATIONS KILLED: {kills}/{len(results)}")
    print("VERDICT:", "PASS" if kills == len(results) else "FAIL")
    return 0 if kills == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
