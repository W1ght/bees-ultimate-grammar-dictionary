"""Independent verbatim re-verification of selected must-fix findings.

Does not trust the LLM or the dossier: greps the FROZEN extracted source JSON for
the exact strings each finding cites, so a maintainer can confirm the defect
exists in source bytes.
"""
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
EXTRACTED = HERE / "evidence" / "extracted"

PROBES = [
    ("にほかならない", "dojg", ["にはかならない", "にほかならない", "ことにほならない"]),
    ("でしょう", "nihongo_net", ["※Nだ", "Nだ + でしょう"]),
    ("でしょう", "edewakaru", ["名詞［辞書形］＋だろう・でしょう"]),
    ("かどうか", "nihongo_net", ["ナA（普通形）だかどうか", "※ナAだ"]),
    ("かどうか", "nihongo_no_sensei", ["な形容詞語幹＋（である／なの）＋かどうか"]),
    ("さえ", "nihongo_net", ["V（ます形）ます + さえあれば", "飲みさえすれば"]),
    ("さえ", "donna_toki", ["Vます＋さえすれば"]),
    ("によって", "nihongo_net", ["×箸でご飯を食べます", "×箸によってご飯を食べます"]),
    ("ないでもない", "nihongo_net", ["ものでもない", "買えないでもない"]),
    ("に至るまで", "nihongo_net", ["に至る", "に至るまで", "彼は死に至った"]),
]


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def main():
    docs = {}
    for p in sorted(EXTRACTED.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        docs[d["source"]] = d["points"]

    out = []
    for expr, src, needles in PROBES:
        rows = [r for r in docs[src] if r["source_id"] == expr or r["expression"] == expr]
        blob = json.dumps(rows, ensure_ascii=False)
        nblob = norm(blob)
        res = {"expression": expr, "source": src, "rowsFound": len(rows), "needles": {}}
        for n in needles:
            res["needles"][n] = {
                "presentVerbatim": n in blob,
                "presentNormalized": norm(n) in nblob,
                "occurrences": blob.count(n),
            }
        out.append(res)
        print(f"--- {expr} @ {src} ({len(rows)} source rows)")
        for n, v in res["needles"].items():
            mark = "FOUND  " if v["presentNormalized"] else "ABSENT "
            print(f"    {mark} x{v['occurrences']:<3} {n!r}")

    (HERE / "evidence" / "independent_reverify.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
