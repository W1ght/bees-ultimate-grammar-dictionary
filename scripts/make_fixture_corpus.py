"""Select representative real-corpus entries for the render fixture.

Run against the UGD-09 merged corpus; writes tests/harness/fixture_corpus.json.
"""

import json
import re
import sys

CORPUS = "/home/skerraut/work/ugd-09-banks/data/merged/corpus.json"
OUT = "tests/harness/fixture_corpus.json"

d = json.load(open(CORPUS, encoding="utf-8"))
entries = d["entries"]
labels = d["sourceLabels"]

RUBY = re.compile(r"<ruby|<rt")
LATIN = re.compile(r"[A-Za-z]")


def fields(c):
    return [c.get(k) or "" for k in ("meaning", "structure", "nuance", "explanation", "notes")]


def has_ruby(e):
    return any(RUBY.search(v) for c in e["contributions"] for v in fields(c))


def english_meaning(e):
    for c in e["contributions"]:
        m = c.get("meaning") or ""
        first = next((line for line in m.splitlines() if line.strip()), "")
        if first and LATIN.search(first) and len(LATIN.findall(first)) > len(first) * 0.3:
            return True
    return False


def n_examples(e):
    return sum(len(c["examples"]) for c in e["contributions"])


def sparse(e):
    c = e["contributions"]
    return (
        len(c) == 1
        and not c[0]["examples"]
        and not c[0]["jlpt"]
        and not c[0]["structure"]
        and not c[0]["explanation"]
    )


picks: dict[str, dict] = {}


def pick(name, candidates, key=None):
    cands = [e for e in candidates if e["expression"] not in {p["expression"] for p in picks.values()}]
    if not cands:
        print(f"!! no candidate for {name}", file=sys.stderr)
        return
    chosen = max(cands, key=key) if key else cands[0]
    picks[name] = chosen
    print(f"{name:22s} -> {chosen['expression']!r} sources={len(chosen['contributions'])} ex={n_examples(chosen)} variants={len(chosen['variants'])}")


multi = [e for e in entries if len({c["source"] for c in e["contributions"]}) >= 3]
pick("multi_source_rich", multi, key=n_examples)
pick("english_gloss", [e for e in entries if english_meaning(e)], key=n_examples)
pick("ruby_furigana", [e for e in entries if has_ruby(e)], key=n_examples)
pick("longest_expression", entries, key=lambda e: len(e["expression"]))
pick("most_variants", entries, key=lambda e: len(e["variants"]))
pick("sparse_minimal", [e for e in entries if sparse(e)], key=lambda e: -len(e["expression"]))
pick("no_jlpt", [e for e in entries if not any(c["jlpt"] for c in e["contributions"]) and n_examples(e) > 2], key=n_examples)

payload = {
    "sourceLabels": labels,
    "corpusEntryCount": len(entries),
    "entries": {name: e for name, e in picks.items()},
}
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
    fh.write("\n")
print("wrote", OUT, len(json.dumps(payload)), "bytes of JSON")
