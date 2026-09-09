"""Mutation proof for verify_findings.py.

Injects hallucinated / malformed findings into a copy of the LLM results and
confirms the verifier REJECTS each one. A verifier that accepts everything the
model says is not a gate.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PY = sys.executable

MUTATIONS = [
    (
        "fabricated_quote",
        lambda f: {**f, "sideA": {**f["sideA"], "quote": "この文型は絶対に使えないと全ての辞書が述べている"}},
    ),
    ("unknown_claimId", lambda f: {**f, "sideB": {**f["sideB"], "claimId": "ghost_source#nonexistent"}}),
    ("invalid_class", lambda f: {**f, "class": "vibes"}),
    ("invalid_confidence", lambda f: {**f, "confidence": "pretty sure"}),
    ("empty_quote", lambda f: {**f, "sideA": {**f["sideA"], "quote": ""}}),
    ("same_claim_both_sides", lambda f: {**f, "class": "meaning", "sideB": dict(f["sideA"])}),
    (
        "translated_quote",
        lambda f: {**f, "sideB": {**f["sideB"], "quote": "this pattern means something else entirely"}},
    ),
    ("missing_side", lambda f: {**f, "sideB": None}),
]


def run_verifier(root):
    r = subprocess.run(
        [PY, str(root / "scripts" / "verify_findings.py")],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if r.returncode != 0:
        return None, r.stderr[-500:]
    data = json.loads((root / "evidence" / "verified_findings.json").read_text(encoding="utf-8"))
    return data, None


def main():
    sandbox = HERE / "evidence" / "_mutation_sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    (sandbox / "scripts").mkdir(parents=True)
    shutil.copy(HERE / "scripts" / "verify_findings.py", sandbox / "scripts")
    shutil.copytree(HERE / "dossiers", sandbox / "dossiers")
    (sandbox / "evidence").mkdir(exist_ok=True)

    # seed with only the results that already have an accepted finding
    base, err = run_verifier(HERE)
    if base is None:
        print("baseline verifier failed:", err)
        return 1
    accepted = base["accepted"]
    if not accepted:
        print("no accepted findings to mutate yet")
        return 1
    seed_files = sorted({a["file"] for a in accepted})[:12]

    results = []
    for name, mut in MUTATIONS:
        dst = sandbox / "evidence" / "llm_findings"
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        # copy ALL results so the completeness gate is unaffected
        for p in (HERE / "evidence" / "llm_findings").glob("*.json"):
            shutil.copy(p, dst)
        mutated = 0
        for fn in seed_files:
            fp = dst / fn
            rec = json.loads(fp.read_text(encoding="utf-8"))
            if not rec.get("findings"):
                continue
            rec["findings"] = [mut(rec["findings"][0])] + rec["findings"][1:]
            fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            mutated += 1
            if mutated >= 3:
                break
        got, err = run_verifier(sandbox)
        if got is None:
            results.append((name, False, f"verifier crashed: {err}"))
            continue
        # the mutated findings must NOT be accepted
        base_accept = len(accepted)
        new_accept = len(got["accepted"])
        killed = new_accept <= base_accept - mutated
        results.append(
            (
                name,
                killed,
                f"mutated={mutated} accepted {base_accept}->{new_accept} "
                f"rejected={len(got['rejected'])}",
            )
        )

    ok = True
    for name, killed, detail in results:
        print(f"  {'KILLED ' if killed else 'SURVIVED'} {name}: {detail}")
        ok = ok and killed
    print(f"\nverifier mutations killed: {sum(1 for _, k, _ in results if k)}/{len(results)}")
    # restore the real verified_findings.json
    run_verifier(HERE)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
