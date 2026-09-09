"""Attribute a card-rendering change: what did it ACTUALLY alter in the archive?

A visual-review round returns findings, not causes. Before a finding can be called
a regression it has to be reproduced in the bytes, and before it can be dismissed
the change has to be shown not to touch what the finding names. This does the
second half mechanically: it diffs two packaged archives headword by headword,
ignoring one named structured-content role, and reports every card that differs
for any OTHER reason.

Used on UGD-08b (which adds a per-source `sourceLevel` row to 158 cards) to
attribute the 13 must-fix findings of beauty-gate round v44: 2,315 of 2,414 cards
were byte-identical to the pre-UGD-08b build once level rows were stripped, the
remaining 99 gained only a level-only disclosure, and nothing else changed -- so
every string those findings named predated the card. The baseline build then
independently reproduced the same findings on the same tiles.

Usage:
    python scripts/diff_packaged_cards.py <baseline.zip> <candidate.zip> [role]

`role` defaults to `sourceLevel`. Exits non-zero when the candidate differs from
the baseline in any way the named role does not explain.

Pitfall this encodes: a `sourceBlock` is `[summary, bodyWrapper]` and a role node
can sit at any depth INSIDE `bodyWrapper`. An earlier version of this probe only
looked at the disclosure's direct children, found the level row nowhere, and so
reported all 1,858 disclosures as changed. Strip recursively.
"""
import json
import sys
import zipfile

BASE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/baseline.zip"
NEW = sys.argv[2] if len(sys.argv) > 2 else "build/bees-ultimate-grammar-dictionary.zip"
ROLE = sys.argv[3] if len(sys.argv) > 3 else "sourceLevel"


def load(path):
    with zipfile.ZipFile(path) as zf:
        rows = []
        for name in sorted(n for n in zf.namelist() if n.startswith("term_bank_")):
            rows.extend(json.loads(zf.read(name)))
        return {r[0]: r for r in rows}


def strip(node):
    """Remove every ROLE subtree, at any depth."""
    if isinstance(node, list):
        return [strip(i) for i in node
                if not (isinstance(i, dict) and ROLE in (i.get("data") or {}))]
    if isinstance(node, dict):
        if ROLE in (node.get("data") or {}):
            return None
        copy = dict(node)
        if "content" in copy:
            copy["content"] = strip(copy["content"])
        return copy
    return node


def blocks(node, out):
    if isinstance(node, dict):
        if node.get("tag") == "details" and "sourceBlock" in (node.get("data") or {}):
            out.append(node)
        blocks(node.get("content"), out)
    elif isinstance(node, list):
        for item in node:
            blocks(item, out)
    return out


def label(block):
    return block["content"][0]["content"][0]["content"]


def canon(node):
    return json.dumps(node, ensure_ascii=False, sort_keys=True)


base = load(BASE)
new = load(NEW)
print(f"baseline {len(base)} cards, new {len(new)} cards")

identical = 0
level_only_gained = 0
cards_gaining = []
problems = []

for head, n in new.items():
    b = base[head]
    n_blocks = {label(x): x for x in blocks(n[5][0]["content"], [])}
    b_blocks = {label(x): x for x in blocks(b[5][0]["content"], [])}

    gained = sorted(set(n_blocks) - set(b_blocks))
    lost = sorted(set(b_blocks) - set(n_blocks))
    if lost:
        problems.append((head, f"LOST disclosure(s): {lost}"))

    # A gained disclosure must contain nothing but its level row.
    for name in gained:
        stripped_body = strip(n_blocks[name]["content"][1])
        remaining = [c for c in (stripped_body.get("content") or []) if c]
        if remaining:
            problems.append((head, f"gained {name!r} with content beyond the role: {canon(remaining)[:90]}"))
        else:
            level_only_gained += 1
    if gained:
        cards_gaining.append(head)

    # Every shared disclosure must be byte-identical once levels are stripped.
    for name in sorted(set(n_blocks) & set(b_blocks)):
        if canon(strip(n_blocks[name])) != canon(b_blocks[name]):
            problems.append((head, f"body of {name!r} changed beyond its {ROLE} node"))

    # And so must the whole card, ignoring gained disclosures.
    if not gained and canon(strip(n[5][0]["content"])) == canon(b[5][0]["content"]):
        identical += 1

print()
print(f"cards byte-identical to baseline once {ROLE} nodes are stripped: {identical}")
print(f"cards that gained a disclosure:                               {len(cards_gaining)}")
print(f"  ... gained disclosures containing ONLY that role:           {level_only_gained}")
print(f"problems:                                                     {len(problems)}")
for row in problems[:12]:
    print("   ", row)

ok = not problems and identical + len(cards_gaining) == len(new)
print()
if ok:
    print(f"PROVEN: outside its {ROLE} nodes, the candidate changed NO card content.")
    print(f"The only structural addition is {level_only_gained} disclosures on "
          f"{len(cards_gaining)} cards")
    print(f"whose entire body is that role.")
    print()
    print("Any visual finding naming other content therefore predates this change; "
          "confirm")
    print("by scoring the same tiles from the baseline build.")
else:
    print(f"NOT clean: identical={identical} gaining={len(cards_gaining)} total={len(new)}")
sys.exit(0 if ok else 1)
