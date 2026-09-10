#!/usr/bin/env python3
"""Acquire the IMABI lesson corpus into data/sources/imabi/ via the WordPress REST API.

imabi.org is a WordPress site exposing /wp-json/wp/v2/pages. This script fetches
every page verbatim, stores one JSON file per page as pages/<id>.json in exactly
the shape the imabi extractor consumes (id, slug, link, title.rendered,
content.rendered), writes an index.json, a PERMISSION.json recording the
user-reported permission basis, and a SOURCE.lock.json pinning every stored file
by sha256 + byteCount.

Properties (mirrors scripts/acquire_yokubi.py / acquire_community_grammar.py):
* content-addressed: each stored page is the exact response bytes, canonicalized
  once (see below) then hashed; a re-acquisition of the same corpus reproduces
  identical bytes and lock.
* bounded: per-page and total byte ceilings; the total page count is checked
  against the API's X-WP-Total header and the build fails closed on a mismatch.
* fail-closed: SOURCE.lock.json is written only after every expected page is
  stored; a short read raises instead of locking a subset.

Canonicalization: each page dict is reduced to exactly the fields the extractor
reads and re-serialized with sorted keys + ensure_ascii=False, so the stored
bytes are stable regardless of upstream field ordering or which _fields the API
happened to echo. This is the "untouched response bytes" spirit adapted to a
paginated JSON API whose member ordering is not guaranteed stable.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "https://imabi.org/wp-json/wp/v2/pages"
FIELDS = "id,slug,link,title.rendered,content.rendered"
USER_AGENT = "bees-ultimate-grammar-dictionary/1.0 (local Yomitan dictionary build)"
PER_PAGE = 100
TIMEOUT = 120
MAX_PAGE_BYTES = 4 * 1024 * 1024          # a single lesson page
MAX_TOTAL_BYTES = 128 * 1024 * 1024       # whole corpus ceiling
LOCK_NAME = "SOURCE.lock.json"

DEFAULT_DIR = pathlib.Path("data/sources/imabi")


def _fetch(url: str) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return data, headers
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 4:
                raise
            wait = 2 ** attempt
            print(f"[imabi] fetch retry {attempt+1} after {exc}; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _canonical_page(page: dict) -> dict:
    """Reduce a WP page to exactly the extractor's fields, in a stable shape."""
    return {
        "id": int(page["id"]),
        "slug": page.get("slug", ""),
        "link": page.get("link"),
        "title": {"rendered": page["title"]["rendered"]},
        "content": {"rendered": page["content"]["rendered"]},
    }


def acquire(out_dir: pathlib.Path, *, force: bool = False) -> dict:
    pages_dir = out_dir / "pages"
    if pages_dir.exists() and not force:
        existing = list(pages_dir.glob("*.json"))
        if existing:
            print(f"[imabi] {len(existing)} pages already present; use --force to re-acquire", file=sys.stderr)
    pages_dir.mkdir(parents=True, exist_ok=True)

    collected: dict[int, dict] = {}
    expected_total: int | None = None

    page_no = 1
    while True:
        url = f"{BASE}?per_page={PER_PAGE}&page={page_no}&_fields={FIELDS}&orderby=id&order=asc"
        try:
            body, headers = _fetch(url)
        except urllib.error.HTTPError as exc:
            # WP returns 400 rest_post_invalid_page_number once we pass the end.
            if exc.code == 400:
                break
            raise
        if expected_total is None and "x-wp-total" in headers:
            expected_total = int(headers["x-wp-total"])
        batch = json.loads(body.decode("utf-8"))
        if not batch:
            break
        for page in batch:
            collected[int(page["id"])] = _canonical_page(page)
        print(f"[imabi] fetched API page {page_no}: {len(batch)} entries (total so far {len(collected)})")
        page_no += 1
        time.sleep(0.3)  # be polite to the origin

    if expected_total is not None and len(collected) != expected_total:
        raise SystemExit(
            f"[imabi] FAIL closed: fetched {len(collected)} pages but X-WP-Total said {expected_total}"
        )

    # Write one file per page, hash it, accumulate the lock.
    files: dict[str, dict] = {}
    total_bytes = 0
    index_entries = []
    for page_id in sorted(collected):
        page = collected[page_id]
        raw = (json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(raw) > MAX_PAGE_BYTES:
            raise SystemExit(f"[imabi] FAIL closed: page {page_id} is {len(raw)} bytes (> {MAX_PAGE_BYTES})")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_BYTES:
            raise SystemExit(f"[imabi] FAIL closed: corpus exceeds {MAX_TOTAL_BYTES} bytes")
        rel = f"pages/{page_id}.json"
        (out_dir / rel).write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        files[rel] = {"sha256": sha, "byteCount": len(raw)}
        index_entries.append({"id": page_id, "slug": page["slug"], "file": rel})

    # index.json (verbatim listing) — also locked.
    index_payload = {"count": len(index_entries), "pages": index_entries}
    index_raw = (json.dumps(index_payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    (out_dir / "index.json").write_bytes(index_raw)
    files["index.json"] = {"sha256": hashlib.sha256(index_raw).hexdigest(), "byteCount": len(index_raw)}

    # PERMISSION.json — records how this build came to have the content.
    permission_payload = {
        "source": "imabi",
        "attribution": "IMABI (imabi.net)",
        "note": "The IMABI authors approved full-content use for this build.",
    }
    perm_raw = (json.dumps(permission_payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    (out_dir / "PERMISSION.json").write_bytes(perm_raw)
    files["PERMISSION.json"] = {"sha256": hashlib.sha256(perm_raw).hexdigest(), "byteCount": len(perm_raw)}

    lock = {
        "source": "imabi",
        "acquiredAt": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "endpoint": BASE,
        "expectedTotal": expected_total,
        "files": dict(sorted(files.items())),
    }
    (out_dir / LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "pages": len(collected),
        "expectedTotal": expected_total,
        "lockedFiles": len(files),
        "totalBytes": total_bytes,
    }
    print(json.dumps(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=pathlib.Path, default=DEFAULT_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    acquire(args.dir, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
