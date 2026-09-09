"""Prove the unified-dataset audit fails closed on a tampered artifact.

An audit that passes on damaged bytes is decoration. Each mutation below breaks
exactly one property the audit claims to enforce; every one must be caught.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable
ART = pathlib.Path("data/merge/unified.jsonl")
STATS = pathlib.Path("data/merge/unified.stats.json")


def run_audit(cwd):
    return subprocess.run(
        [PY, "scripts/audit_unified.py"], cwd=cwd, capture_output=True, text=True
    )


def mutate(lines, kind):
    entries = [json.loads(line) for line in lines]
    if kind == "drop-a-point-entry":
        for index, entry in enumerate(entries):
            if entry["kind"] == "point":
                del entries[index]
                break
    elif kind == "delete-examples-from-a-contribution":
        for entry in entries:
            for sense in entry.get("senses") or []:
                for contribution in sense["contributions"]:
                    if contribution.get("examples"):
                        contribution["examples"] = contribution["examples"][:-1]
                        return [json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for e in entries]
    elif kind == "point-a-redirect-at-nothing":
        for entry in entries:
            if entry["kind"] == "redirect":
                entry["redirectTargets"] = ["この形は存在しない"]
                break
    elif kind == "reconcile-a-jlpt-conflict":
        for entry in entries:
            if len(entry.get("jlptLevels") or []) > 1:
                entry["jlptLevels"] = entry["jlptLevels"][:1]
                break
    elif kind == "misorder-ordinal-senses":
        for entry in entries:
            senses = entry.get("senses") or []
            if len(senses) >= 10 and all(
                s["disambiguator"].startswith("sense") for s in senses
            ):
                entry["senses"] = [senses[-1]] + senses[:-1]
                break
    elif kind == "duplicate-a-contribution":
        for entry in entries:
            for sense in entry.get("senses") or []:
                sense["contributions"].append(dict(sense["contributions"][0]))
                return [json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for e in entries]
    else:
        raise AssertionError(kind)
    return [
        json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for e in entries
    ]


MUTATIONS = (
    "drop-a-point-entry",
    "delete-examples-from-a-contribution",
    "point-a-redirect-at-nothing",
    "reconcile-a-jlpt-conflict",
    "misorder-ordinal-senses",
    "duplicate-a-contribution",
)


def main():
    baseline = run_audit(REPO)
    if baseline.returncode != 0:
        print("PRISTINE AUDIT FAILED -- fix that first")
        print(baseline.stdout[-2000:])
        return 1
    print("OK   pristine artifact passes the audit")

    lines = (REPO / ART).read_text(encoding="utf-8").splitlines()
    survived = []
    for kind in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp) / "repo"
            work.mkdir()
            for path in ("src", "scripts", "data"):
                shutil.copytree(REPO / path, work / path, symlinks=True)
            (work / ART).write_text(
                "".join(f"{line}\n" for line in mutate(lines, kind)), encoding="utf-8"
            )
            result = run_audit(work)
            if result.returncode == 0:
                survived.append(kind)
                print(f"SURVIVED  {kind}  <-- the audit does NOT catch this")
            else:
                failed = [
                    line.split(":", 1)[0].removeprefix("FAIL").strip()
                    for line in result.stdout.splitlines()
                    if line.startswith("FAIL")
                ]
                print(f"caught    {kind}  -> {failed or ['(raised)']}")

    print()
    print("SURVIVING MUTATIONS:", survived if survived else "none")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
