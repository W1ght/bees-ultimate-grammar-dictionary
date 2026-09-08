"""Command-line entrypoint: `python3 -m bugd.cli <stage>`."""

from __future__ import annotations

import argparse
import pathlib
import sys

from .jsonio import dump_json
from .pipeline import (
    DEFAULT_BUILD_DIR,
    DEFAULT_EXTRACTED_DIR,
    DEFAULT_MERGED_DIR,
    DEFAULT_SOURCES_DIR,
    run_build,
    run_extract,
    run_merge,
    run_validate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugd", description="Build Bee's Ultimate Grammar Dictionary"
    )
    parser.add_argument("--sources-dir", type=pathlib.Path, default=DEFAULT_SOURCES_DIR)
    parser.add_argument("--extracted-dir", type=pathlib.Path, default=DEFAULT_EXTRACTED_DIR)
    parser.add_argument("--merged-dir", type=pathlib.Path, default=DEFAULT_MERGED_DIR)
    parser.add_argument("--build-dir", type=pathlib.Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--revision", default=None, help="explicit YYYY.MM.DD[.N] revision")
    parser.add_argument("--source", action="append", dest="only", help="limit extract to a source")

    subparsers = parser.add_subparsers(dest="stage", required=True)
    for stage in ("extract", "merge", "build", "validate", "all"):
        subparsers.add_parser(stage)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stage = args.stage

    if stage in ("extract", "all"):
        result = run_extract(
            sources_dir=args.sources_dir, extracted_dir=args.extracted_dir, only=args.only
        )
        print(f"[extract] {dump_json(result)}")

    if stage in ("merge", "all"):
        if not args.extracted_dir.is_dir():
            print(
                f"[merge] no extracted artifacts at {args.extracted_dir}; nothing to merge",
                file=sys.stderr,
            )
        else:
            print(f"[merge] {dump_json(run_merge(extracted_dir=args.extracted_dir, merged_dir=args.merged_dir))}")

    if stage in ("build", "all"):
        result = run_build(
            merged_dir=args.merged_dir, build_dir=args.build_dir, revision=args.revision
        )
        print(
            f"[build] {result['zipPath']} revision={result['revision']} "
            f"entries={result['entries']} bytes={result['byteCount']} "
            f"sha256={str(result['sha256'])[:12]}"
        )

    if stage in ("validate", "all"):
        ok, failures = run_validate(build_dir=args.build_dir)
        for failure in failures:
            print(f"[validate] FAIL: {failure}", file=sys.stderr)
        if not ok:
            return 1
        print("[validate] pinned Yomitan schema validation passed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
