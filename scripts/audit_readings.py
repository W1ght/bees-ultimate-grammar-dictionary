"""Reading audit gate, run as part of `make merge`.

Two fail-closed checks against the emitted unified dataset (data/merge/unified.jsonl):

1. **Plausibility gate (fail-closed).** Every kanji-bearing contribution
   `reading` must be a structurally possible kana rendering of its own
   `expression` (bugd.readings.is_plausible_reading). A new structural violation
   fails the build. This is the last-line guard the nine UGD-11c-B corrections
   were about; it catches structurally impossible readings (e.g. 結構->けっか),
   not context/sense reading errors (which only semantic review can catch — see
   the module docstring).

2. **Cross-source reading agreement (report + fail-closed on regressions).**
   Where two sources give the same written expression a *different* reading, the
   pair is surfaced. Genuine multi-reading expressions (甲斐 かい/がい,
   如何 いかん/いかが) are expected; the check fails only if a disagreement's
   readings are not BOTH plausible for the expression, i.e. one source is
   shipping an impossible reading the plausibility gate would also flag.

Writes data/merge/reading_audit.json for review. Exits non-zero on any failure.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.readings import has_kanji, is_plausible_reading  # noqa: E402

UNIFIED = pathlib.Path("data/merge/unified.jsonl")
REPORT = pathlib.Path("data/merge/reading_audit.json")


#: Rows whose expression is a descriptive LABEL rather than a headword, so no
#: kana-coverage rule can relate it to the reading. Each is listed explicitly, with
#: its exact reading, so the allowance cannot widen silently: a new row, or a
#: changed reading on this row, still fails the gate.
#:
#: `可能の形 （～れる・～られる）` / `～れる（かのう）` is NINJAL prose describing the
#: potential form, with the suffixes parenthesised; the reading inverts that and
#: parenthesises the sense tag instead. The label 可能の形 reads かのうのかたち. Scoped
#: by measurement: exactly 1 of 1,513 kanji-bearing rows carrying a reading.
DESCRIPTIVE_LABELS = {
    ("ninjal_bunkei", "可能の形 （～れる・～られる）", "～れる（かのう）"),
}


def _contributions(entries):
    for entry in entries:
        for sense in entry.get("senses", []):
            for contribution in sense.get("contributions", []):
                yield contribution


def main() -> int:
    entries = [json.loads(line) for line in UNIFIED.read_text(encoding="utf-8").splitlines() if line.strip()]

    # 1. Plausibility gate.
    checked = 0
    implausible = []
    allowed_labels: list[dict[str, object]] = []
    # 2. Cross-source disagreement: expression -> {reading -> sources}
    by_expr: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))

    for contribution in _contributions(entries):
        expression = contribution.get("expression") or ""
        reading = contribution.get("reading")
        if reading:
            by_expr[expression][reading].add(contribution.get("source", ""))
        if not has_kanji(expression) or not reading:
            continue
        checked += 1
        if not is_plausible_reading(expression, reading):
            source = contribution.get("source")
            if (source, expression, reading) in DESCRIPTIVE_LABELS:
                allowed_labels.append(
                    {"source": source, "expression": expression, "reading": reading}
                )
                continue
            implausible.append(
                {
                    "source": source,
                    "expression": expression,
                    "reading": reading,
                }
            )

    disagreements = []
    disagreement_failures = []
    for expression, readings in sorted(by_expr.items()):
        if len(readings) < 2:
            continue
        variants = sorted(readings)
        # Every reading of a disagreement must itself be plausible; an impossible
        # one is a real defect (and the plausibility gate above already caught it
        # if it is kanji-bearing).
        bad = [
            r
            for r in variants
            if has_kanji(expression)
            and not is_plausible_reading(expression, r)
            and not any(
                expression == allowed_expression and r == allowed_reading
                for _, allowed_expression, allowed_reading in DESCRIPTIVE_LABELS
            )
        ]
        record = {
            "expression": expression,
            "readings": {r: sorted(readings[r]) for r in variants},
            "allPlausible": not bad,
        }
        disagreements.append(record)
        if bad:
            disagreement_failures.append({"expression": expression, "implausible": bad})

    REPORT.write_text(
        json.dumps(
            {
                "checkedKanjiReadings": checked,
                "implausibleReadings": implausible,
                "allowedDescriptiveLabels": allowed_labels,
                "readingDisagreements": disagreements,
                "disagreementCount": len(disagreements),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"[reading-audit] checked {checked} kanji-bearing readings")
    print(f"[reading-audit] cross-source reading disagreements: {len(disagreements)}")
    ok = True
    if allowed_labels:
        print(
            f"[reading-audit] allowed {len(allowed_labels)} descriptive-label row(s) "
            "(expression is prose, not a headword):"
        )
        for item in allowed_labels:
            print(f"    {item['source']} · {item['expression']} -> {item['reading']}")
    # A stale allowance is a defect too: if a listed row no longer reaches the gate
    # (re-homed, corrected, or dropped) the entry must be removed rather than left
    # silently widening the gate for a future row that happens to match it.
    unused = sorted(DESCRIPTIVE_LABELS - {
        (item["source"], item["expression"], item["reading"]) for item in allowed_labels
    })
    if unused:
        ok = False
        print(
            f"[reading-audit] FAIL: {len(unused)} DESCRIPTIVE_LABELS entr(ies) matched no "
            "implausible row; the corpus changed, so remove the stale allowance:"
        )
        for source, expression, reading in unused:
            print(f"    {source} · {expression} -> {reading}")
    if implausible:
        ok = False
        print(f"[reading-audit] FAIL: {len(implausible)} structurally implausible reading(s):")
        for item in implausible:
            print(f"    {item['source']} · {item['expression']} -> {item['reading']}")
    if disagreement_failures:
        ok = False
        print(f"[reading-audit] FAIL: {len(disagreement_failures)} disagreement(s) carry an implausible reading:")
        for item in disagreement_failures:
            print(f"    {item['expression']} -> implausible {item['implausible']}")
    if ok:
        print(f"[reading-audit] OK — wrote {REPORT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
