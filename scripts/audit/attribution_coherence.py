"""Stricter attribution audit + mutation proof.

Part 1 (single-row coherence): for each merged contribution, require that ONE
single extracted row contains every claim byte. A contribution whose claims are
only satisfiable by UNIONING two different source rows means the merge blended
two distinct source records into one attributed claim -- exactly the drift class
the union-based check cannot see.

Part 2 (mutation proof): inject known drift into a copy of the merged data and
confirm the checks fail. A green audit on unmutated bytes is not evidence the
audit can detect anything.
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
#: UGD-16: this probe was written against UGD-11d's frozen evidence copy, whose
#: paths do not exist in the repository. To be a reusable regression it must read
#: the artifacts the build actually produces, so both inputs are now CLI arguments
#: defaulting to the live pipeline outputs. Point them at a frozen copy to
#: reproduce a historical measurement.
REPO = Path(__file__).resolve().parents[2]
DEFAULT_UNIFIED = REPO / "data" / "merge" / "unified.jsonl"
DEFAULT_EXTRACTED = REPO / "data" / "extracted"
TEXT_FIELDS = ("meaning", "structure", "explanation", "notes", "jlpt", "reading", "expression")


def norm(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def strings_of(v, out):
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, list):
        for x in v:
            strings_of(x, out)
    elif isinstance(v, dict):
        for x in v.values():
            strings_of(x, out)


def row_blob(row):
    parts = []
    strings_of(row, parts)
    return norm(" \u0001 ".join(parts))


def load_candidates(extracted: Path):
    candidates = defaultdict(list)
    for path in sorted(Path(extracted).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for r in doc["points"]:
            candidates[(doc["source"], r["source_id"])].append(row_blob(r))
    return candidates


def audit(entries, candidates):
    """Return (stats, findings). Every claim must fit inside ONE row blob."""
    stats = {"contributions": 0, "claims": 0}
    findings = defaultdict(list)
    for e in entries:
        if e["kind"] != "point":
            continue
        for sense in e["senses"]:
            for c in sense["contributions"]:
                stats["contributions"] += 1
                key = (c["source"], c["sourceId"])
                blobs = candidates.get(key)
                if not blobs:
                    findings["missing_source_row"].append(
                        {"entryId": e["entryId"], "key": list(key)}
                    )
                    continue
                claims = []
                for f in TEXT_FIELDS:
                    v = c.get(f)
                    if isinstance(v, str) and v.strip():
                        claims.append((f, norm(v)))
                for ex in c.get("examples", []):
                    jp = norm(ex.get("japanese"))
                    if jp:
                        claims.append(("example", jp))
                stats["claims"] += len(claims)
                # rows that satisfy EVERY claim
                coherent = [i for i, b in enumerate(blobs) if all(cv in b for _, cv in claims)]
                if coherent:
                    continue
                unmatched = [
                    (f, cv) for f, cv in claims if not any(cv in b for b in blobs)
                ]
                rec = {
                    "entryId": e["entryId"],
                    "source": key[0],
                    "sourceId": key[1],
                    "candidateRows": len(blobs),
                    "claims": len(claims),
                }
                if unmatched:
                    rec["unmatched_claims"] = [
                        {"field": f, "value": cv[:220]} for f, cv in unmatched[:4]
                    ]
                    rec["unmatched_count"] = len(unmatched)
                    findings["claim_in_no_candidate_row"].append(rec)
                else:
                    # every claim matched some row, but no single row matched all
                    findings["claims_span_multiple_rows"].append(rec)
    return stats, findings


def main():
    import argparse
    import hashlib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unified", nargs="?", type=Path, default=DEFAULT_UNIFIED)
    parser.add_argument("--extracted", type=Path, default=DEFAULT_EXTRACTED)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    unified = args.unified
    if not unified.is_file():
        raise SystemExit(f"no unified artifact at {unified}; run `make merge` first")
    blob = unified.read_bytes()
    entries = [json.loads(line) for line in blob.decode("utf-8").splitlines() if line.strip()]
    candidates = load_candidates(args.extracted)
    if not candidates:
        raise SystemExit(f"no extracted artifacts under {args.extracted}; run `make extract` first")

    stats, findings = audit(entries, candidates)
    summary = {
        "target": {
            "path": str(unified),
            "sha256": hashlib.sha256(blob).hexdigest(),
        },
        "stats": stats,
        "counts": {k: len(v) for k, v in sorted(findings.items())},
    }
    out = args.out or (unified.parent / "attribution_coherence.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"summary": summary, "findings": findings}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("=== UNMUTATED ===")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for k, v in sorted(findings.items()):
        if v:
            print(f"\n--- {k} ({len(v)}) first 8 ---")
            for item in v[:8]:
                print(json.dumps(item, ensure_ascii=False)[:600])

    # ---- Part 2: mutation proof -------------------------------------------
    print("\n=== MUTATION PROOF (each must be DETECTED) ===")
    import copy

    def first_point_with(pred):
        for e in entries:
            if e["kind"] == "point" and pred(e):
                return e
        return None

    results = []

    # M1: swap a claim between two sources (classic misattribution)
    m = copy.deepcopy(entries)
    donor = recipient = None
    for e in m:
        if e["kind"] != "point":
            continue
        cs = [c for s in e["senses"] for c in s["contributions"] if c.get("meaning")]
        if len({c["source"] for c in cs}) >= 2:
            donor, recipient = cs[0], cs[1]
            break
    original = recipient["meaning"]
    recipient["meaning"] = donor["meaning"]
    _, f = audit(m, candidates)
    detected = bool(f["claim_in_no_candidate_row"] or f["claims_span_multiple_rows"])
    results.append(("M1 cross-source meaning swap", detected, sum(len(v) for v in f.values())))

    # M2: fabricate a meaning no source asserts
    m = copy.deepcopy(entries)
    for e in m:
        if e["kind"] == "point" and e["senses"][0]["contributions"][0].get("meaning"):
            e["senses"][0]["contributions"][0]["meaning"] = "FABRICATED GLOSS NOT IN ANY SOURCE"
            break
    _, f = audit(m, candidates)
    detected = any("FABRICATED" in json.dumps(v, ensure_ascii=False) for v in f.values())
    results.append(("M2 fabricated gloss", detected, sum(len(v) for v in f.values())))

    # M3: repoint a contribution to a different sourceId
    m = copy.deepcopy(entries)
    tgt = None
    for e in m:
        if e["kind"] != "point":
            continue
        for s in e["senses"]:
            for c in s["contributions"]:
                if len(c.get("examples", [])) >= 3 and c.get("explanation"):
                    tgt = c
                    break
            if tgt:
                break
        if tgt:
            break
    tgt["sourceId"] = "\u3059\u308b"  # a real but different id
    _, f = audit(m, candidates)
    detected = sum(len(v) for v in f.values()) > 0
    results.append(("M3 sourceId repoint", detected, sum(len(v) for v in f.values())))

    # M4: inject an example from a foreign source row
    m = copy.deepcopy(entries)
    src_ex = None
    for e in m:
        if e["kind"] == "point":
            for s in e["senses"]:
                for c in s["contributions"]:
                    if c.get("examples"):
                        src_ex = c["examples"][0]
                        break
                if src_ex:
                    break
        if src_ex:
            break
    for e in reversed(m):
        if e["kind"] == "point":
            c = e["senses"][0]["contributions"][0]
            if c["source"] != src_ex:
                c.setdefault("examples", []).append(dict(src_ex))
                break
    _, f = audit(m, candidates)
    detected = sum(len(v) for v in f.values()) > 0
    results.append(("M4 foreign example injection", detected, sum(len(v) for v in f.values())))

    ok = True
    for name, detected, n in results:
        print(f"  {'KILLED ' if detected else 'SURVIVED'} {name} (findings={n})")
        ok = ok and detected
    print(f"\nmutations killed: {sum(1 for _, d, _ in results if d)}/{len(results)}")

    # ---- Part 3: fail closed on an UNEXPLAINED finding ---------------------
    # UGD-16: as a Makefile gate this must exit nonzero on a real defect, not just
    # on a surviving mutant. The reading overlay is applied at contribution
    # assembly, deliberately AFTER keymap alignment, so a corrected reading cannot
    # match the extracted row by construction -- those findings are expected. Every
    # OTHER finding, and any reading finding whose value is not the overlay's own
    # `to` value, is a genuine misattribution.
    overlay_path = REPO / "data" / "corrections" / "readings.json"
    expected: set[tuple[str, str, str]] = set()
    if overlay_path.is_file():
        for correction in json.loads(overlay_path.read_text(encoding="utf-8"))["corrections"]:
            expected.add((correction["source"], correction["source_id"], correction["to"]))

    unexplained = []
    for bucket, items in sorted(findings.items()):
        for item in items:
            claims = item.get("unmatched_claims") or []
            if (
                bucket == "claim_in_no_candidate_row"
                and len(claims) == 1
                and claims[0]["field"] == "reading"
                and (item["source"], item["sourceId"], claims[0]["value"]) in expected
            ):
                continue
            unexplained.append({"bucket": bucket, **item})

    explained = sum(len(v) for v in findings.values()) - len(unexplained)
    print(
        f"\nfindings: {sum(len(v) for v in findings.values())} "
        f"(explained by the reading overlay: {explained}, unexplained: {len(unexplained)})"
    )
    for item in unexplained[:10]:
        print("  UNEXPLAINED " + json.dumps(item, ensure_ascii=False)[:400])
    if unexplained:
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
