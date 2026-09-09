"""Build one side-by-side dossier per multi-source canonical group.

Every dossier contains VERBATIM source text only -- no paraphrase, no summary --
so an LLM flag can always cite both sides exactly and a human can re-verify.
Each claim is addressable as <source>#<sourceId>#<field> so a finding is
mechanically checkable back against the frozen dataset.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
UNIFIED = HERE / "evidence" / "unified.frozen.jsonl"
OUT = HERE / "dossiers"

CLAIM_FIELDS = ("jlpt", "meaning", "structure", "explanation", "notes")
# markers a source uses to label a sentence right or wrong
MARK = re.compile(
    r"[\u00d7\u2715\u2716\u274c\u25cb\u25ce\u2713\u2714\u25b3\uff58]"
    r"|\u8aa4\u7528|NG|\u4f7f\u3048\u306a\u3044|\u9593\u9055"
)


def build(entry):
    """Return dossier dict for a multi-source point entry, or None."""
    if entry["kind"] != "point":
        return None
    contribs = [(s, c) for s in entry["senses"] for c in s["contributions"]]
    if len({c["source"] for _, c in contribs}) < 2:
        return None

    senses = []
    for sense in entry["senses"]:
        srcs = []
        for c in sense["contributions"]:
            claims = {}
            for f in CLAIM_FIELDS:
                v = c.get(f)
                if isinstance(v, str) and v.strip():
                    claims[f] = v
            ex = []
            for i, x in enumerate(c.get("examples", [])):
                jp = x.get("japanese") or ""
                item = {"i": i, "ja": jp}
                if x.get("english"):
                    item["en"] = x["english"]
                if MARK.search(jp):
                    item["hasCorrectnessMarker"] = True
                ex.append(item)
            srcs.append(
                {
                    "claimId": f"{c['source']}#{c['sourceId']}",
                    "source": c["source"],
                    "sourceLabel": c["sourceLabel"],
                    "sourceId": c["sourceId"],
                    "tags": c.get("tags") or [],
                    "claims": claims,
                    "examples": ex,
                }
            )
        senses.append(
            {
                "canonicalKey": sense["canonicalKey"],
                "disambiguator": sense.get("disambiguator") or "",
                "sources": srcs,
            }
        )

    return {
        "entryId": entry["entryId"],
        "expression": entry["expression"],
        "reading": entry.get("reading"),
        "axes": entry.get("axes"),
        "entryJlptLevels": entry.get("jlptLevels"),
        "entryObservedRegisters": entry.get("observedRegisters"),
        "entryObservedSignatures": entry.get("observedSignatures"),
        "sourceCount": len({c["source"] for _, c in contribs}),
        "senses": senses,
    }


def main():
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    sizes = []
    manifest = []
    for line in UNIFIED.open(encoding="utf-8"):
        d = build(json.loads(line))
        if d is None:
            continue
        blob = json.dumps(d, ensure_ascii=False, indent=1)
        name = f"{len(manifest):04d}.json"
        (OUT / name).write_text(blob, encoding="utf-8")
        sizes.append(len(blob))
        manifest.append(
            {
                "file": name,
                "entryId": d["entryId"],
                "sourceCount": d["sourceCount"],
                "chars": len(blob),
                "senses": len(d["senses"]),
                "markedExamples": sum(
                    1
                    for s in d["senses"]
                    for src in s["sources"]
                    for e in src["examples"]
                    if e.get("hasCorrectnessMarker")
                ),
            }
        )
    (HERE / "evidence" / "dossier_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    sizes.sort()
    print(
        json.dumps(
            {
                "dossiers": len(manifest),
                "total_chars": sum(sizes),
                "min": sizes[0],
                "median": sizes[len(sizes) // 2],
                "p90": sizes[int(0.9 * len(sizes))],
                "max": sizes[-1],
                "over_60k": sum(1 for s in sizes if s > 60000),
                "entries_with_marked_examples": sum(1 for m in manifest if m["markedExamples"]),
                "total_marked_examples": sum(m["markedExamples"] for m in manifest),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
