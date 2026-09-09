"""Deterministic label-conflict pre-audit (JLPT / register / formation shape).

These conflicts are mechanically detectable. Their EXISTENCE is not a defect --
two sources may legitimately place different senses at different levels -- so
this stage only enumerates candidates with both sides cited verbatim. Whether a
candidate is a genuine contradiction is decided later with evidence.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
UNIFIED = HERE / "evidence" / "unified.frozen.jsonl"

LEVEL = re.compile(r"\bN[1-5]\b")


def main():
    jlpt_conflicts = []
    register_conflicts = []
    seen_entries = 0

    for line in UNIFIED.open(encoding="utf-8"):
        e = json.loads(line)
        if e["kind"] != "point":
            continue
        contribs = [(s, c) for s in e["senses"] for c in s["contributions"]]
        if len({c["source"] for _, c in contribs}) < 2:
            continue
        seen_entries += 1

        # ---- JLPT: group declared levels by source, and by sense ----------
        by_source = defaultdict(set)
        per_claim = []
        for sense, c in contribs:
            raw = c.get("jlpt")
            if not isinstance(raw, str) or not raw.strip():
                continue
            levels = set(LEVEL.findall(raw))
            if not levels:
                continue
            by_source[c["source"]] |= levels
            per_claim.append(
                {
                    "claimId": f"{c['source']}#{c['sourceId']}",
                    "sense": sense["canonicalKey"],
                    "verbatim_jlpt": raw,
                    "levels": sorted(levels),
                }
            )

        if len(by_source) >= 2:
            union = set().union(*by_source.values())
            if len(union) > 1:
                # cross-source disagreement only when two sources name
                # non-identical level sets
                sets = {s: frozenset(v) for s, v in by_source.items()}
                distinct = set(sets.values())
                if len(distinct) > 1:
                    jlpt_conflicts.append(
                        {
                            "entryId": e["entryId"],
                            "entryJlptLevels": e.get("jlptLevels"),
                            "levelsBySource": {s: sorted(v) for s, v in by_source.items()},
                            "sameSenseSpan": len(
                                {c["sense"] for c in per_claim}
                            ) == 1,
                            "claims": per_claim,
                        }
                    )

        # ---- register/formality tags -------------------------------------
        reg_by_source = defaultdict(set)
        for _sense, c in contribs:
            for t in c.get("tags") or []:
                reg_by_source[c["source"]].add(t)
        if e.get("observedRegisters") and len(e["observedRegisters"]) > 1:
            register_conflicts.append(
                {
                    "entryId": e["entryId"],
                    "observedRegisters": e["observedRegisters"],
                    "tagsBySource": {s: sorted(v) for s, v in reg_by_source.items()},
                }
            )

    out = {
        "multiSourceEntries": seen_entries,
        "jlptConflictCandidates": len(jlpt_conflicts),
        "jlptConflictsSameSense": sum(1 for c in jlpt_conflicts if c["sameSenseSpan"]),
        "registerSpreadCandidates": len(register_conflicts),
    }
    (HERE / "evidence" / "label_conflicts.json").write_text(
        json.dumps(
            {
                "summary": out,
                "jlptConflicts": jlpt_conflicts,
                "registerSpread": register_conflicts,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(out, indent=1))
    print("\n--- first 6 JLPT conflict candidates ---")
    for c in jlpt_conflicts[:6]:
        print(
            c["entryId"],
            c["levelsBySource"],
            "sameSense" if c["sameSenseSpan"] else "acrossSenses",
        )


if __name__ == "__main__":
    main()
