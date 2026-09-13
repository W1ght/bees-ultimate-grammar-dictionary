#!/usr/bin/env python3
"""Acquire the HJGP (日本語文型辞典) monolingual source into `data/sources/hjgp/`.

Source: HuangAntimony/Nihongo-Bunkei-Jiten, a rebuild of the Japanese grammar
dictionary from mefat.review. 1,087 headwords (957 full entries + 130 cross-
references), monolingual Japanese with rich furigana, structured senses,
subsenses, and ~9,200 example sentences.

Three files are acquired:

* ``dict.json`` — entry-id → HTML content mapping (1,088 keys including a
  ``version`` integer)
* ``toc.json``  — ordered keyword → id table of contents (1,087 entries)
* ``trans.json`` — Vietnamese translation overlays (carried in provenance, not
  rendered as a gloss; same policy as nihongo_no_sensei's Chinese)

Usage:
    python3 scripts/acquire_hjgp.py [--force]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"

USER_AGENT = "bees-ultimate-grammar-dictionary/acquire (+local build)"
TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 256 * 1024 * 1024

HJGP_COMMIT = "35308928ed5cffb3a8b2f2709a54b59b896748cf"
HJGP_RAW = (
    f"https://raw.githubusercontent.com/HuangAntimony/Nihongo-Bunkei-Jiten"
    f"/{HJGP_COMMIT}/raw/jitendex-yomitan"
)

# The extractor consumes the published Yomitan banks.  The repository also
# contains the producer's internal dict/toc/trans files, but those are not the
# locked input used by this project and do not have the Yomitan row shape.
FILES = {
    f"term_bank_{number}.json": f"{HJGP_RAW}/term_bank_{number}.json"
    for number in range(1, 215)
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeError(f"response exceeds {MAX_RESPONSE_BYTES} bytes: {url}")
    if not payload:
        raise RuntimeError(f"empty response: {url}")
    return payload


def acquire(*, force: bool) -> dict[str, object]:
    directory = SOURCES_DIR / "hjgp"
    if force:
        for path in directory.glob("term_bank_*.json"):
            path.unlink()
    directory.mkdir(parents=True, exist_ok=True)

    # Raw GitHub serves each bank independently.  Fetch concurrently so a
    # 214-bank source does not take several minutes on a high-latency link.
    def fetch_one(item: tuple[str, str]) -> tuple[str, bytes]:
        relative_path, url = item
        local = directory / relative_path
        if not force and local.is_file():
            return relative_path, local.read_bytes()
        return relative_path, fetch(url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        extracted = dict(pool.map(fetch_one, sorted(FILES.items())))

    files: dict[str, dict[str, object]] = {}
    for relative_path, url in sorted(FILES.items()):
        target = directory / relative_path
        payload = extracted[relative_path]
        target.write_bytes(payload)
        files[relative_path] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byteCount": len(payload),
            "url": url,
        }

    lock = {
        "source": "hjgp",
        "acquiredAt": datetime.datetime.now(datetime.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "provenance": {
            "upstreamRepository": "https://github.com/HuangAntimony/Nihongo-Bunkei-Jiten",
            "upstreamCommit": HJGP_COMMIT,
            "producer": "https://www.mefat.review/bunkei.ziten.html",
        },
        "files": files,
    }
    (directory / "SOURCE.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even when bytes already exist",
    )
    args = parser.parse_args(argv)
    try:
        lock = acquire(force=args.force)
    except (urllib.error.URLError, RuntimeError, OSError) as error:
        print(f"[acquire] FAIL hjgp: {error}", file=sys.stderr)
        return 1
    total = sum(int(entry["byteCount"]) for entry in lock["files"].values())
    print(f"[acquire] hjgp: {len(lock['files'])} files, {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
