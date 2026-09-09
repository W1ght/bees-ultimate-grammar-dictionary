"""Verify the PACKAGED bytes now carry every source's own JLPT level.

Reads the archive, not the renderer, so this proves what a user installs. For
each of the 158 conflicting entries it walks the term-bank card and checks that
every (source, level) pair the DATASET attributes is visible inside that source's
own disclosure -- and that the compact badge is still exactly one line.
"""
import json
import sys
import zipfile
from collections import Counter

ZIP = "build/bees-ultimate-grammar-dictionary.zip"

with zipfile.ZipFile(ZIP) as zf:
    entries = []
    for name in sorted(n for n in zf.namelist() if n.startswith("term_bank_")):
        entries.extend(json.loads(zf.read(name)))

unified = [json.loads(line) for line in open("data/merge/unified.jsonl", encoding="utf-8")]
by_head = {e[0]: e for e in entries}

fail = []


def check(label, got, want):
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fail.append(label)


def disclosures(node, out):
    if isinstance(node, dict):
        if node.get("tag") == "details" and "sourceBlock" in (node.get("data") or {}):
            out.append(node)
        disclosures(node.get("content"), out)
    elif isinstance(node, list):
        for item in node:
            disclosures(item, out)
    return out


def role_values(node, role, out):
    if isinstance(node, dict):
        if role in (node.get("data") or {}):
            content = node.get("content")
            if isinstance(content, str):
                out.append(content)
        role_values(node.get("content"), role, out)
    elif isinstance(node, list):
        for item in node:
            role_values(item, role, out)
    return out


def find_role(node, role, out):
    if isinstance(node, dict):
        if role in (node.get("data") or {}):
            out.append(node)
        find_role(node.get("content"), role, out)
    elif isinstance(node, list):
        for item in node:
            find_role(item, role, out)
    return out


conflicts = [u for u in unified if len(u.get("jlptLevels") or []) > 1]
check("conflicting-level entries in the dataset", len(conflicts), 158)

incomplete = []
compact_badge_counts = Counter()
disclosure_level_rows = 0

for u in conflicts:
    card = by_head[u["expression"]][5][0]["content"]

    expected = {}
    for sense in u["senses"]:
        for c in sense["contributions"]:
            if c.get("jlpt"):
                expected.setdefault(c["sourceLabel"], set()).add(c["jlpt"])

    seen = {}
    for block in disclosures(card, []):
        label = block["content"][0]["content"][0]["content"]
        levels = set(role_values(block["content"][1:], "jlpt", []))
        if levels:
            seen[label] = levels

    if seen != expected:
        incomplete.append((u["expression"], expected, seen))

    compact = card["content"][0]
    assert "compact" in compact["data"], u["expression"]
    compact_badge_counts[len(role_values(compact, "jlpt", []))] += 1

check("every conflict shows each source's own level in that source's disclosure", incomplete[:5], [])
check("compact badge cardinality across the 158 conflicts", dict(compact_badge_counts), {1: 158})

visible = Counter()
for u in conflicts:
    card = by_head[u["expression"]][5][0]["content"]
    levels = set()
    for block in disclosures(card, []):
        levels |= set(role_values(block["content"][1:], "jlpt", []))
    visible[len(levels)] += 1
print(f"      distinct levels visible in disclosures, per conflict: {dict(sorted(visible.items()))}")
check("no conflict shows fewer than 2 levels below the fold", sorted(visible)[0] >= 2, True)

# Corpus-wide: the level row is present wherever a source asserts one, and the
# role never leaks outside a source disclosure.
rows_total = 0
rows_outside = 0
for entry in entries:
    card = entry[5][0]["content"]
    rows = find_role(card, "sourceLevel", [])
    rows_total += len(rows)
    inside = sum(len(find_role(b["content"][1:], "sourceLevel", [])) for b in disclosures(card, []))
    rows_outside += len(rows) - inside
print(f"      sourceLevel rows packaged: {rows_total}")
check("no sourceLevel row outside a source disclosure", rows_outside, 0)

# Frozen-contract invariants that the new admission rule could have broken.
both = []
crossref_or_listed = []
for entry in entries:
    card = entry[5][0]["content"]
    has_block = bool(disclosures(card, []))
    has_fallback = bool(find_role(card, "crossref", []) or find_role(card, "listedOnly", []))
    if has_block and has_fallback:
        both.append(entry[0])
check("contract invariant 4: no row has BOTH a sourceBlock and a compact fallback", both[:5], [])

bare = []
for entry in entries:
    card = entry[5][0]["content"]
    children = card["content"]
    # invariant 6: the Sources disclosure is never the only visible content
    visible_children = [
        c for c in children
        if not (isinstance(c, dict) and c.get("tag") == "details" and not c.get("data"))
    ]
    meaningful = [
        c for c in visible_children
        if not (isinstance(c, dict) and "compact" in (c.get("data") or {}) and not c.get("content"))
    ]
    if not meaningful:
        bare.append(entry[0])
check("contract invariant 6: no card is only a Sources disclosure", bare[:5], [])

sizes = Counter(len(b["content"]) for e in entries for b in disclosures(e[5][0]["content"], []))
check("contract invariant 8: every sourceBlock has exactly summary + body", dict(sizes), {2: sum(sizes.values())})

print()
print("FAILURES:", fail if fail else "none")
sys.exit(1 if fail else 0)
