"""Render the human-readable ambiguity report from data/merge/keymap.json.

keymap.json carries the machine-readable report; this renders the part a reviewer
actually reads: what folded, what was refused, and why.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="render the matcher's ambiguity report")
    parser.add_argument("--keymap", type=pathlib.Path, default=pathlib.Path("data/merge/keymap.json"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/merge/AMBIGUITY.md"))
    parser.add_argument("--examples", type=int, default=25, help="refusals to list per guard")
    args = parser.parse_args(argv)

    payload = json.loads(args.keymap.read_text(encoding="utf-8"))
    report = payload["report"]
    points = payload["points"]
    lines: list[str] = []
    add = lines.append

    add("# Cross-source grammar-point matching — ambiguity report")
    add("")
    add(f"Generated from `{args.keymap}`. Every number here is measured, not estimated.")
    add("")

    corpus = report["corpus"]
    add("## Corpus")
    add("")
    add("| stage | rows |")
    add("| --- | --- |")
    add(f"| source rows read | {corpus['rows']} |")
    add(f"| producer-declared alias/redirect rows demoted | {corpus['declaredAliasRows']} |")
    add(f"| byte-identical duplicate rows collapsed | {corpus['duplicateRowsCollapsed']} |")
    add(f"| **substantive rows matched** | **{corpus['substantiveRows']}** |")
    add(f"| **canonical grammar points** | **{len(points)}** |")
    add("")
    add("Contributions per source after demotion and duplicate collapse:")
    add("")
    add("| source | rows |")
    add("| --- | --- |")
    for name, count in corpus["contributionsBySource"].items():
        add(f"| {name} | {count} |")
    add("")
    counts = report["canonicalPoints"]
    add(
        f"{counts['multiSource']} points are corroborated by more than one source; "
        f"{counts['singleSource']} come from a single source."
    )
    add("")

    tier_a = report["tierA"]
    add("## Tier A — partition-scoped bijection")
    add("")
    add(f"Rule: {tier_a['rule']}.")
    add("")
    add(f"- **{tier_a['bijectiveBuckets']}** buckets folded (a bijection across sources).")
    add(
        f"- **{tier_a['refusedCollisionBuckets']}** cross-source collisions **refused**: at least "
        "one source contributed several senses, so which sense the other source's row "
        "corresponds to is unanswerable from the data."
    )
    add(f"- **{tier_a['singleSourceBuckets']}** buckets are single-source (nothing to align).")
    add("")
    add("Disambiguator basis for rows that did not fold:")
    add("")
    add("| basis | rows |")
    add("| --- | --- |")
    for basis, count in tier_a["disambiguatorBasis"].items():
        add(f"| {basis} | {count} |")
    add("")
    add(
        "`signature` = the sources state different attachment; `form` = different written "
        "headword normalizing alike; `sense` = nothing observable separates them, so an "
        "ordinal is used rather than pretending to know how they differ."
    )
    add("")
    add(f"### Refused cross-source collisions ({len(tier_a['refusedCollisions'])})")
    add("")
    add("| key | rows | sources | resulting keys |")
    add("| --- | --- | --- | --- |")
    for item in tier_a["refusedCollisions"][: args.examples]:
        sources = ", ".join(f"{k}×{v}" for k, v in item["sources"].items())
        keys = ", ".join(f"`{k}`" for k in item["canonicalKeys"][:4])
        add(f"| `{item['bucketKey']}` | {item['rowCount']} | {sources} | {keys} |")
    if len(tier_a["refusedCollisions"]) > args.examples:
        add(f"| … | | | _{len(tier_a['refusedCollisions']) - args.examples} more in keymap.json_ |")
    add("")

    tier_b = report["tierB"]
    add("## Tier B — producer-attested variant links")
    add("")
    add(f"Rule: {tier_b['rule']}.")
    add("")
    add(f"**{tier_b['accepted']} accepted**, by evidence:")
    add("")
    for reason, count in tier_b["acceptedByReason"].items():
        add(f"- `{reason}` — {count}")
    add("")
    add(f"**{tier_b['refused']} refused**, by guard:")
    add("")
    add("| guard | refused | what it protects |")
    add("| --- | --- | --- |")
    explanations = {
        "polarity-flip": "an affirmative and its negation are opposite points",
        "generic-hub": "a key many rows point at is a copula, not a variant claim",
        "one-way-different-reading": "a one-way link between differently-read forms is relatedness",
        "chained-not-pairwise": "transitive closure blew a chain up into one 8-row point",
        "key-too-short": "single-character particle keys appear inside unrelated points",
    }
    for guard, count in tier_b["refusedByGuard"].items():
        add(f"| `{guard}` | {count} | {explanations.get(guard, '')} |")
    add("")
    add(f"Transitive closure: {tier_b['transitiveClosure']}.")
    add("")
    add(f"### Accepted links ({len(tier_b['acceptedLinks'])})")
    add("")
    add("| left | right | evidence |")
    add("| --- | --- | --- |")
    for link in tier_b["acceptedLinks"][: args.examples]:
        add(f"| `{link['leftKey']}` | `{link['rightKey']}` | {link['reason']} |")
    if len(tier_b["acceptedLinks"]) > args.examples:
        add(f"| … | | _{len(tier_b['acceptedLinks']) - args.examples} more_ |")
    add("")
    add("### Refused links, grouped by guard")
    add("")
    by_guard: dict[str, list[dict[str, object]]] = collections.defaultdict(list)
    for item in tier_b["refusedLinks"]:
        by_guard[str(item["guard"])].append(item)
    for guard in sorted(by_guard):
        items = by_guard[guard]
        add(f"#### `{guard}` ({len(items)})")
        add("")
        for item in items[: args.examples]:
            add(f"- `{item['leftExpression']}` ↮ `{item['rightExpression']}`")
        if len(items) > args.examples:
            add(f"- _… {len(items) - args.examples} more_")
        add("")

    aliases = report["aliases"]
    add("## Producer-declared aliases")
    add("")
    add(f"Rule: {aliases['rule']}.")
    add("")
    add("| resolution | rows |")
    add("| --- | --- |")
    for resolution, count in aliases["byResolution"].items():
        add(f"| {resolution} | {count} |")
    add("")
    add(
        "`polarity-flip` and `ambiguous-target` rows contribute **no** lookup form: attaching "
        "them would either show the opposite grammar point or guess which of several senses "
        "the producer meant. `unresolved` rows name a target this corpus does not contain."
    )
    add("")

    add("## Deliberate non-gates")
    add("")
    for name, note in report["notFoldGates"].items():
        add(f"- **{name}** — {note}")
    add("")

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes, {len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
