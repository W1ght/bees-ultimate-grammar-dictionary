"""Assert the PACKAGED bytes carry the merge's work.

A green merge suite plus a green build does not prove the ZIP a user installs
contains attributed multi-source cards and working redirects. This reads the
archive itself.
"""

import json
import re
import sys
import zipfile
from collections import Counter

ZIP = "build/bees-ultimate-grammar-dictionary.zip"

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'OK ' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fail.append(label)


with zipfile.ZipFile(ZIP) as zf:
    banks = [n for n in zf.namelist() if n.startswith("term_bank_")]
    entries = []
    for name in sorted(banks):
        entries.extend(json.loads(zf.read(name)))
    tag_bank = json.loads(zf.read("tag_bank_1.json"))
    index = json.loads(zf.read("index.json"))

unified = [json.loads(line) for line in open("data/merge/unified.jsonl", encoding="utf-8")]
stats = json.load(open("data/merge/unified.stats.json", encoding="utf-8"))

check("packaged term entries == unified entries", len(entries), len(unified))
check(
    "sequences are 1..N with no gaps",
    [e[6] for e in entries] == list(range(1, len(entries) + 1)),
    True,
)

headwords = [e[0] for e in entries]
# A headword may legitimately appear twice: the partition axes keep a classical
# point separate from its modern homograph (27 real pairs -- `ごとし`, `すら`,
# `お`...). Yomitan keys on (expression, reading) and shows both, so identity is
# the ENTRY ID, not the written form.
check("no duplicate unified entry id", len({u["entryId"] for u in unified}) == len(unified), True)
dupe_heads = {h for h in headwords if headwords.count(h) > 1}
axis_split = {
    u["expression"]
    for u in unified
    if u["expression"] in dupe_heads and u["axes"] != {"variety": "standard", "era": "modern"}
}
check("every duplicated headword is an axis split", dupe_heads == axis_split, True)
check("every unified expression is packaged", set(headwords) == {e["expression"] for e in unified}, True)

# per-source attribution actually rendered
def walk(node, out):
    if isinstance(node, dict):
        if node.get("tag") == "details" and "sourceBlock" in (node.get("data") or {}):
            out.append(node)
        walk(node.get("content"), out)
    elif isinstance(node, list):
        for item in node:
            walk(item, out)


by_head = {e[0]: e for e in entries}
labels = set(stats["corpus"]["sourceLabels"].values())

multi = [u for u in unified if u["kind"] == "point" and len({c["source"] for s in u["senses"] for c in s["contributions"]}) >= 4]
check("corpus has 4+-source entries to check", len(multi) >= 100, True)

worst = max(multi, key=lambda u: len({c["source"] for s in u["senses"] for c in s["contributions"]}))
blocks = []
walk(by_head[worst["expression"]][5][0]["content"], blocks)
rendered = set()
for b in blocks:
    summary = b["content"][0]["content"]
    if isinstance(summary, list):
        rendered.add(summary[0]["content"])
expected = {
    c["sourceLabel"] for s in worst["senses"] for c in s["contributions"]
}
print(f"      probe entry {worst['expression']!r}: {len(expected)} sources")
check("every contributing source has its own labelled disclosure", rendered, expected)
check("rendered labels are real source labels", rendered <= labels, True)

# redirects render as a clickable crossref, not an empty card
redirects = [u for u in unified if u["kind"] == "redirect"]
check("redirects present", len(redirects), stats["unified"]["redirectEntries"])
missing_link = []
for u in redirects:
    text = json.dumps(by_head[u["expression"]], ensure_ascii=False)
    target = u["redirectTargets"][0]
    if f"?query={target}" not in text:
        missing_link.append(u["expression"])
check("every redirect card links its target", missing_link, [])

# a redirect must not be an empty card
empty = [u["expression"] for u in redirects if "crossref" not in json.dumps(by_head[u["expression"]], ensure_ascii=False)]
check("no redirect card lacks a crossref block", empty, [])

# Conflicting JLPT levels must survive into the DATASET with attribution AND be
# readable in the packaged card. The compact block stays one badge by design
# (banks._compact_block takes the first contribution that supplies a level,
# because that block is deliberately one line), so the disagreement is disclosed
# where each source speaks: banks._source_level_block emits the source's own
# level inside its own `sourceBlock`. UGD-08b landed that; `audit_packaged_jlpt.py`
# proves it per entry over all 253.
#
# Repinned 158 -> 253 by UGD-16 convergence, which landed the five remaining
# extractors. Attributed mechanically rather than on the total: recomputing the
# conflict set over the ORIGINAL five sources alone gives 156, plus 97 entries that
# only conflict once a new source joins = 253, with ZERO entries that conflicted
# under the original five and no longer do. The residual 158 -> 156 on that basis is
# UGD-11c-A's polarity repair renaming headwords out of the set (なくもある ->
# なくもない etc.), so no disagreement was destroyed. The behaviour assertions below
# passed on all 253 before this cardinality was touched.
conf = [u for u in unified if len(u.get("jlptLevels") or []) > 1]
check("conflicting-level entries packaged", len(conf), 253)
bad = []
for u in conf:
    per_source = {
        (c["source"], c["jlpt"])
        for s in u["senses"]
        for c in s["contributions"]
        if c.get("jlpt")
    }
    if len({lv for _, lv in per_source}) < 2:
        bad.append(u["expression"])
check("every conflict keeps >1 attributed level in the dataset", bad, [])
probe = conf[0]
print(
    f"      probe {probe['expression']!r}: dataset levels {probe['jlptLevels']}, "
    f"per source "
    + str(sorted({(c['source'], c['jlpt']) for s in probe['senses'] for c in s['contributions'] if c.get('jlpt')}))
)
# The compact badge is single-valued on purpose; every level the dataset carries
# must nevertheless be present in the packaged card, below the fold.
card = json.dumps(by_head[probe["expression"]], ensure_ascii=False)
rendered = [lv for lv in probe["jlptLevels"] if f'"{lv}"' in card]
check("the packaged card carries every level the dataset attributes", rendered, probe["jlptLevels"])


def _compact_of(entry):
    return entry[5][0]["content"]["content"][0]


def _levels(node, out):
    if isinstance(node, dict):
        if "jlpt" in (node.get("data") or {}) and isinstance(node.get("content"), str):
            out.append(node["content"])
        _levels(node.get("content"), out)
    elif isinstance(node, list):
        for item in node:
            _levels(item, out)
    return out


check(
    "the compact block still shows exactly one JLPT badge",
    Counter(len(_levels(_compact_of(by_head[u["expression"]]), [])) for u in conf),
    Counter({1: 253}),
)

# tag bank still names every source
check("tag bank covers every source", len(tag_bank), len(stats["corpus"]["sources"]))
check("index attributes every source", all(lb in index.get("attribution", "") for lb in labels), True)

# no AI field leaked into a rendered glossary (corpus has none, but prove it)
check("no aiGenerated key in packaged banks", "aiGenerated" in json.dumps(entries), False)

print()
print("FAILURES:", fail if fail else "none")
sys.exit(1 if fail else 0)
