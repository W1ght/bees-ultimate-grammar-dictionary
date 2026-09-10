"""Command-line entrypoint: `python3 -m bugd.cli <stage>`."""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import unify
from .jsonio import dump_json
from .reading_corrections import (
    DEFAULT_CORRECTIONS_PATH as DEFAULT_READING_CORRECTIONS_PATH,
)
from .pipeline import (
    DEFAULT_BUILD_DIR,
    DEFAULT_DIST_DIR,
    DEFAULT_EXTRACTED_DIR,
    DEFAULT_MERGED_DIR,
    DEFAULT_SOURCES_DIR,
    SchemaValidationError,
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
    parser.add_argument(
        "--corrections-dir",
        type=pathlib.Path,
        default=None,
        help="directory of confirmed post-extraction content corrections "
        "(default: data/corrections/content; a missing directory means no corrections)",
    )
    parser.add_argument("--merged-dir", type=pathlib.Path, default=DEFAULT_MERGED_DIR)
    parser.add_argument(
        "--keymap",
        type=pathlib.Path,
        default=None,
        help="cross-source keymap the merge resolves rows through "
        f"(default: {unify.DEFAULT_KEYMAP_PATH})",
    )
    parser.add_argument(
        "--unified",
        type=pathlib.Path,
        default=None,
        help="where to write the unified dataset "
        f"(default: {unify.DEFAULT_UNIFIED_PATH})",
    )
    parser.add_argument("--build-dir", type=pathlib.Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--dist-dir", type=pathlib.Path, default=DEFAULT_DIST_DIR)
    parser.add_argument(
        "--no-dist",
        action="store_true",
        help="build and validate without publishing to the dist directory",
    )
    parser.add_argument(
        "--require-entries",
        action="store_true",
        help="fail closed unless the archive carries at least one term entry",
    )
    parser.add_argument("--revision", default=None, help="explicit YYYY.MM.DD[.N] revision")
    parser.add_argument("--source", action="append", dest="only", help="limit extract to a source")
    corrections = parser.add_mutually_exclusive_group()
    corrections.add_argument(
        "--reading-corrections",
        type=pathlib.Path,
        default=None,
        dest="reading_corrections",
        help="reading-correction overlay the merge applies "
        f"(default: {DEFAULT_READING_CORRECTIONS_PATH})",
    )
    corrections.add_argument(
        "--no-reading-corrections",
        action="store_const",
        const=False,
        dest="reading_corrections",
        help="merge with NO reading corrections. For a caller that builds a "
        "deliberately isolated corpus the canonical overlay does not describe: "
        "the overlay is keyed to a specific extraction and fails closed when a "
        "correction matches nothing, so such a caller must DECLARE its narrower "
        "corpus rather than the gate being weakened for everyone.",
    )

    subparsers = parser.add_subparsers(dest="stage", required=True)
    for stage in ("extract", "merge", "build", "validate", "all"):
        subparsers.add_parser(stage)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stage = args.stage

    if stage in ("extract", "all"):
        result = run_extract(
            sources_dir=args.sources_dir,
            extracted_dir=args.extracted_dir,
            only=args.only,
            corrections_dir=args.corrections_dir,
        )
        print(f"[extract] {dump_json(result)}")

    if stage in ("merge", "all"):
        extracted = (
            sorted(args.extracted_dir.glob("*.json"))
            if args.extracted_dir.is_dir()
            else []
        )
        if not extracted:
            # Nothing to merge is not an error while sources are still landing:
            # the build stage emits a valid empty-corpus ZIP so packaging and
            # schema validation stay exercisable. Requiring a keymap here would
            # make `all` fail on an empty corpus for the wrong reason.
            print(
                f"[merge] no extracted artifacts at {args.extracted_dir}; nothing to merge",
                file=sys.stderr,
            )
        else:
            print(
                "[merge] "
                + dump_json(
                    run_merge(
                        extracted_dir=args.extracted_dir,
                        merged_dir=args.merged_dir,
                        keymap_path=args.keymap,
                        unified_path=args.unified,
                        # `None` disables the overlay; the default (flag absent)
                        # keeps the canonical one.
                        corrections_path=(
                            None
                            if args.reading_corrections is False
                            else (
                                args.reading_corrections
                                or DEFAULT_READING_CORRECTIONS_PATH
                            )
                        ),
                    )
                )
            )

    if stage in ("build", "all"):
        try:
            result = run_build(
                merged_dir=args.merged_dir,
                build_dir=args.build_dir,
                dist_dir=None if args.no_dist else args.dist_dir,
                revision=args.revision,
                require_entries=args.require_entries,
            )
        except SchemaValidationError as error:
            # Fail closed: report every failure and publish nothing.
            print(f"[build] {error}", file=sys.stderr)
            return 1
        print(
            f"[build] {result['zipPath']} revision={result['revision']} "
            f"entries={result['termEntries']} bytes={result['byteCount']}"
        )
        print(f"[build] sha256={result['sha256']}")
        if result.get("distPath"):
            print(f"[build] published {result['distPath']}")

    if stage in ("validate", "all"):
        ok, failures = run_validate(
            build_dir=args.build_dir, require_entries=args.require_entries
        )
        for failure in failures:
            print(f"[validate] FAIL: {failure}", file=sys.stderr)
        if not ok:
            return 1
        print("[validate] pinned Yomitan schema validation passed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
