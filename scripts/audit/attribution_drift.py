"""Deterministic attribution-drift audit (fixed row identity).

`source_id` is NOT unique within a source (up to 22 extracted rows share one id),
so a contribution's (source, sourceId) selects a CANDIDATE SET of source rows.
Every claim byte in a merged contribution must be present in at least one row of
that candidate set. A claim that is absent from the whole set is drift.

Additionally reports how many contributions have an ambiguous (>1 row) identity,
which bounds how precisely attribution can be verified at all.

Fail-closed: unmatched claims are reported, never assumed benign.
"""
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
UNIFIED = HERE / "evidence" / "unified.frozen.jsonl"
EXTRACTED = HERE / "evidence" / "extracted"

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


def main():
    candidates = defaultdict(list)
    per_source_rows = defaultdict(list)
    for path in sorted(EXTRACTED.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        src = doc["source"]
        for r in doc["points"]:
            candidates[(src, r["source_id"])].append(r)
            per_source_rows[src].append(r)

    cand_blob = {k: " \u0001 ".join(row_blob(r) for r in v) for k, v in candidates.items()}
    src_blob = {s: " \u0001 ".join(row_blob(r) for r in v) for s, v in per_source_rows.items()}

    findings = defaultdict(list)
    stats = {
        "contributions": 0,
        "ambiguous_identity_contributions": 0,
        "text_fields": 0,
        "examples": 0,
    }
    ambiguity_hist = defaultdict(int)

    for line in UNIFIED.open(encoding="utf-8"):
        e = json.loads(line)
        if e["kind"] != "point":
            continue
        for sense in e["senses"]:
            for c in sense["contributions"]:
                stats["contributions"] += 1
                key = (c["source"], c["sourceId"])
                rows = candidates.get(key)
                if not rows:
                    findings["missing_source_row"].append(
                        {"entryId": e["entryId"], "source": key[0], "sourceId": key[1]}
                    )
                    continue
                ambiguity_hist[len(rows)] += 1
                if len(rows) > 1:
                    stats["ambiguous_identity_contributions"] += 1
                blob = cand_blob[key]

                for f in TEXT_FIELDS:
                    val = c.get(f)
                    if not isinstance(val, str) or not val.strip():
                        continue
                    stats["text_fields"] += 1
                    nv = norm(val)
                    if nv in blob:
                        continue
                    rec = {
                        "entryId": e["entryId"],
                        "source": key[0],
                        "sourceId": key[1],
                        "candidateRows": len(rows),
                        "field": f,
                        "merged_value": val[:400],
                    }
                    others = [s for s, jb in src_blob.items() if s != key[0] and nv in jb]
                    if others:
                        rec["also_present_in_sources"] = others
                        findings["field_found_only_in_other_source"].append(rec)
                    else:
                        findings["field_in_no_source"].append(rec)

                for ex in c.get("examples", []):
                    stats["examples"] += 1
                    jp = norm(ex.get("japanese"))
                    if not jp or jp in blob:
                        continue
                    rec = {
                        "entryId": e["entryId"],
                        "source": key[0],
                        "sourceId": key[1],
                        "candidateRows": len(rows),
                        "japanese": (ex.get("japanese") or "")[:300],
                    }
                    others = [s for s, jb in src_blob.items() if s != key[0] and jp in jb]
                    if others:
                        rec["also_present_in_sources"] = others
                        findings["example_found_only_in_other_source"].append(rec)
                    else:
                        findings["example_in_no_source"].append(rec)

    summary = {
        "stats": dict(stats),
        "identity_ambiguity_histogram": {str(k): v for k, v in sorted(ambiguity_hist.items())},
        "counts": {k: len(v) for k, v in sorted(findings.items())},
    }
    (HERE / "evidence" / "attribution_drift.json").write_text(
        json.dumps({"summary": summary, "findings": findings}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for k, v in sorted(findings.items()):
        if v:
            print(f"\n--- {k} (first 6 of {len(v)}) ---")
            for item in v[:6]:
                print(json.dumps(item, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
