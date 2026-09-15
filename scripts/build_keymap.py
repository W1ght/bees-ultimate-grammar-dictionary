"""Emit data/merge/keymap.json from the normalized per-source artifacts."""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from bugd.jsonio import dump_json  # noqa: E402
from bugd.keymap import build_keymap  # noqa: E402
from bugd.keymap_io import KEYMAP_NAME, parse_keymap  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build the cross-source canonical keymap")
    parser.add_argument("--extracted-dir", type=pathlib.Path, default=pathlib.Path("data/extracted"))
    parser.add_argument("--merge-dir", type=pathlib.Path, default=pathlib.Path("data/merge"))
    args = parser.parse_args(argv)

    payload = build_keymap(args.extracted_dir)

    # Round-trip through the reader the merge stage uses, so an artifact that the
    # consumer would reject never reaches disk.
    mapping = parse_keymap(payload)
    if len(mapping) != len(payload["assignments"]):
        raise SystemExit(
            f"identity collision: {len(payload['assignments'])} assignments collapsed "
            f"to {len(mapping)} identities"
        )

    args.merge_dir.mkdir(parents=True, exist_ok=True)
    path = args.merge_dir / KEYMAP_NAME
    path.write_text(dump_json(payload) + "\n", encoding="utf-8", newline="\n")

    report = payload["report"]
    corpus = report["corpus"]
    points = payload["points"]
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(
        f"  rows={corpus['rows']} substantive={corpus['substantiveRows']} "
        f"aliases={corpus['declaredAliasRows']} dupCollapsed={corpus['duplicateRowsCollapsed']}"
    )
    print(f"  canonical points={len(points)} {report['canonicalPoints']}")
    print(f"  tierA={ {k: v for k, v in report['tierA'].items() if isinstance(v, (int, dict))} }")
    print(
        f"  tierB accepted={report['tierB']['accepted']} {report['tierB']['acceptedByReason']} "
        f"refused={report['tierB']['refused']} {report['tierB']['refusedByGuard']}"
    )
    print(f"  aliases={report['aliases']['byResolution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
