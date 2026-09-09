"""Corpus-wide scan for cross-entry paste corruption in `structure` fields.

Two adjudicated must-fix/should-fix findings pointed at the same mechanism: a
source's structure formula names a DIFFERENT grammar point than the entry it sits
on (nihongo_net's ないでもない structure ends in ものでもない; its かいがあって
structure says あげく). If that is a systematic producer defect rather than two
accidents, it is worth its own fix card.

Method: for each contribution with both an expression and a structure, check
whether the structure mentions the entry's own headword (or any of the entry's
lookup forms). Report contributions whose structure mentions ANOTHER entry's
headword but never its own -- the signature of a paste from a neighbouring entry.

Fail-closed on false positives: a headword that is a substring of another
headword would fire spuriously, so a foreign headword only counts when it is
LONGER than the own headword and the own headword is genuinely absent.
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
UNIFIED = HERE / "evidence" / "unified.frozen.jsonl"


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def main():
    entries = [json.loads(l) for l in UNIFIED.open(encoding="utf-8")]
    headwords = set()
    for e in entries:
        if e["kind"] == "point":
            headwords.add(norm(e["expression"]))
            for f in e.get("lookupForms", []):
                headwords.add(norm(f))
    headwords = {h for h in headwords if len(h) >= 3}

    suspects = []
    checked = 0
    by_source = Counter()
    by_class = Counter()
    for e in entries:
        if e["kind"] != "point":
            continue
        own_forms = {norm(e["expression"])} | {norm(f) for f in e.get("lookupForms", [])}
        own_forms = {f for f in own_forms if f}
        own_max = max((len(f) for f in own_forms), default=0)
        for sense in e["senses"]:
            for c in sense["contributions"]:
                st = c.get("structure")
                if not isinstance(st, str) or not st.strip():
                    continue
                checked += 1
                nst = norm(st)
                if any(f and f in nst for f in own_forms):
                    continue
                foreign = sorted(
                    (h for h in headwords if h in nst and len(h) > own_max),
                    key=len,
                    reverse=True,
                )
                if not foreign:
                    continue
                # False-positive class measured on this corpus: the canonical
                # headword is a DERIVED/FOLDED variant of the form the sources
                # actually write (entry `ずにはいる` vs structure `ずにはいられない`,
                # `からって` vs `からといって`). There the structure legitimately
                # names its own point under a fuller name, so it is not a paste
                # from a neighbouring entry. Detect it by shared affixes.
                def related(h):
                    return any(
                        (f and (f in h or h in f))
                        or (len(f) >= 3 and (h.startswith(f[:3]) or h.endswith(f[-3:])))
                        for f in own_forms
                    )

                unrelated = [h for h in foreign if not related(h)]
                klass = "unrelated_headword" if unrelated else "derived_variant_name"
                by_source[c["source"]] += 1
                by_class[klass] += 1
                suspects.append(
                    {
                        "entryId": e["entryId"],
                        "claimId": f"{c['source']}#{c['sourceId']}",
                        "source": c["source"],
                        "class": klass,
                        "sense": sense["canonicalKey"],
                        "ownForms": sorted(own_forms)[:4],
                        "foreignHeadwordsInStructure": foreign[:3],
                        "unrelatedHeadwords": unrelated[:3],
                        "structure": st[:220],
                    }
                )

    summary = {
        "structureFieldsChecked": checked,
        "suspectContributions": len(suspects),
        "bySource": dict(by_source),
        "byClass": dict(by_class),
        "distinctEntries": len({s["entryId"] for s in suspects}),
    }
    (HERE / "evidence" / "structure_paste_scan.json").write_text(
        json.dumps({"summary": summary, "suspects": suspects}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n--- unrelated_headword suspects (real paste candidates) ---")
    for s in [x for x in suspects if x["class"] == "unrelated_headword"]:
        print(
            f"{s['entryId']:<14} {s['claimId']:<28} foreign={s['foreignHeadwordsInStructure']}"
        )
        print(f"    structure: {s['structure'][:130]!r}")


if __name__ == "__main__":
    main()
