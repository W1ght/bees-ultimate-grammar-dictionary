"""Mutation check for the Yokubi artifact tests.

A green suite shows the artifacts are produced; it does not show a regression
would be caught. Each mutation removes or breaks one shipped behaviour; the
suite must fail for every one, otherwise that behaviour is untested.

Pristine text comes from git, never from disk, so an interrupted run cannot
"restore" a mutation as if it were the original.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = "src/bugd/sources/yokubi.py"

MUTATIONS: list[tuple[str, str, str]] = [
    (
        "jsonl never written",
        "        self.write_jsonl(points)\n",
        "",
    ),
    (
        "coverage never written",
        "        self.write_coverage(result)\n",
        "",
    ),
    (
        "coverage omits the skipped-lesson reason",
        "f\"| {row['lesson']} | [{row['title']}]({row['lessonUrl']}) | {row['reason']} |\"",
        "f\"| {row['lesson']} | [{row['title']}]({row['lessonUrl']}) | |\"",
    ),
    (
        "coverage omits covered headwords",
        'heads = ", ".join(f"`{head}`" for head in row["headwords"])',
        'heads = ""',
    ),
    (
        "coverage accounting gate removed",
        "    if len(covered) + len(skipped) != listed:",
        "    if False:",
    ),
    (
        "skipped example groups lose their lesson attribution",
        '                skip["lesson"] = number\n',
        "",
    ),
    (
        "jsonl loses trailing newline per record",
        'dump_json(point_to_json(point)) + "\\n" for point in points',
        "dump_json(point_to_json(point)) for point in points",
    ),
    (
        "jsonl drops provenance attribution",
        '                            "attribution": YOKUBI_ATTRIBUTION,\n',
        "",
    ),
    # These three keep the stats key present and only stop the REPORT from
    # rendering it. An earlier version of the suite asserted the key existed in
    # stats, which passed while the rendered cell was empty.
    (
        "report stops naming the lesson of a skipped example group",
        "lines.append(f\"| {row['lesson']} | `{row['shape']}` | {text} | {row['reason']} |\")",
        "lines.append(f\"| | `{row['shape']}` | {text} | {row['reason']} |\")",
    ),
    (
        "report renders an empty headword cell",
        'f"| {row[\'lesson\']} | [{row[\'title\']}]({row[\'lessonUrl\']}) | {heads} "',
        'f"| {row[\'lesson\']} | [{row[\'title\']}]({row[\'lessonUrl\']}) |  "',
    ),
    (
        "covered table drops its attached-example count",
        "f\"| {row['examplesAttached']} |\"",
        'f"|  |"',
    ),
]


def pristine() -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{TARGET}"], cwd=ROOT, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise SystemExit(f"cannot read pristine {TARGET} from git: {out.stderr}")
    return out.stdout


def run_suite() -> tuple[bool, str]:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_source_yokubi.py", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    failed = re.findall(r"^FAILED (\S+)", out.stdout, re.M)
    return out.returncode == 0, ", ".join(f.split("::")[-1] for f in failed[:3])


def main() -> int:
    path = ROOT / TARGET
    base = pristine()
    on_disk = path.read_text(encoding="utf-8")
    if on_disk != base:
        print("NOTE: working tree differs from HEAD; mutating the committed text")

    survivors = []
    try:
        for name, old, new in MUTATIONS:
            if old not in base:
                print(f"ERROR  {name}: mutation target not found in HEAD text")
                survivors.append(name)
                continue
            path.write_text(base.replace(old, new, 1), encoding="utf-8")
            passed, failures = run_suite()
            if passed:
                print(f"SURVIVED  {name}  <-- untested behaviour")
                survivors.append(name)
            else:
                print(f"killed    {name}  ({failures or 'error'})")
    finally:
        path.write_text(on_disk, encoding="utf-8")

    print()
    if survivors:
        print(f"{len(survivors)}/{len(MUTATIONS)} mutations SURVIVED: {survivors}")
        return 1
    print(f"all {len(MUTATIONS)} mutations killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
