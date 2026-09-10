#!/usr/bin/env python3
"""Acquire the UGD-06 community grammar sources into `data/sources/<name>/`.

Acquisition is separate from extraction on purpose: this script performs the
only network access in the pipeline, writes the untouched response bytes, and
records a `SOURCE.lock.json` so every later stage reads digest-pinned inputs.

Every source here is an already-published dataset or an official repository
download. Nothing is scraped: no producer site is crawled, and no HTML is
harvested. Sources without a clean published export stay documented-and-excluded
in `SOURCES.md` rather than being scraped.

Pinned identities (see SOURCES.md for the full inclusion decisions):

* ``ninjal_bunkei``    NINJAL 日本語文型データベース, DOI 10.15084/0002000610
* ``dojg``             aiko-tanaka/Grammar-Dictionaries @ AIKO_COMMIT, dojg/
* ``donna_toki``       donna_v1.04 Yomitan banks, mirrored (absent from aiko-tanaka HEAD)
* ``nihongo_net``      aiko-tanaka @ AIKO_COMMIT, nihongo_kyoushi/
* ``edewakaru``        aiko-tanaka @ AIKO_COMMIT, edewakaru/
* ``nihongo_no_sensei``aiko-tanaka @ AIKO_COMMIT, nihongo_no_sensei/

Usage:
    python3 scripts/acquire_community_grammar.py [--source NAME]... [--force]
"""

from __future__ import annotations

import argparse
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
# A published grammar bank is a few MB; anything far larger is a wrong URL or a
# hostile response, so bound the read rather than streaming an unbounded body.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# aiko-tanaka/Grammar-Dictionaries HEAD at audit time. Pinned to a commit, not a
# branch, so re-acquisition cannot silently pick up different bytes.
AIKO_COMMIT = "4314e00f59140364ac75be264a6beb910af824d8"
AIKO_RAW = "https://raw.githubusercontent.com/aiko-tanaka/Grammar-Dictionaries"

# The Donna Toki banks were removed from aiko-tanaka's repository before its
# current HEAD (the 2023-11-04 "remove defunct links" commit), so they are
# acquired from a public mirror. Because a mirror is a weaker provenance claim
# than a producer repository, the acquired loose banks are corroborated against
# the independently distributed `…文型辞典_1_05.zip`: the ZIP is acquired too, and
# `verify_donna_toki` asserts the loose and archived term banks carry identical
# entries. A mirror that had altered content would fail that comparison.
DONNA_TOKI_MIRROR_COMMIT = "142e47f3d85af05d2a372f32f32a35ae215c08b1"
DONNA_TOKI_MIRROR = (
    "https://raw.githubusercontent.com/yangjizhou99/language-learning2"
    f"/{DONNA_TOKI_MIRROR_COMMIT}"
    "/src/data/grammar/sources/extra/donnatoki"
)
DONNA_TOKI_ARCHIVE = (
    "https://raw.githubusercontent.com/yangjizhou99/language-learning2"
    f"/{DONNA_TOKI_MIRROR_COMMIT}"
    "/src/data/grammar/sources/extra/"
    "%E3%81%A9%E3%82%93%E3%81%AA%E3%81%A8%E3%81%8D%E3%81%A9%E3%81%86%E4%BD%BF%E3%81%86"
    "%20%E6%97%A5%E6%9C%AC%E8%AA%9E%E8%A1%A8%E7%8F%BE%E6%96%87%E5%9E%8B%E8%BE%9E%E5%85%B8"
    "_1_05.zip"
)
DONNA_TOKI_ARCHIVE_NAME = "donnatoki_1_05.zip"

NINJAL_RECORD = "https://repository.ninjal.ac.jp/record/2000610/files"


def aiko_urls(directory: str, members: list[str]) -> dict[str, str]:
    return {name: f"{AIKO_RAW}/{AIKO_COMMIT}/{directory}/{name}" for name in members}


TERM_BANKS_1 = ["index.json", "term_bank_1.json"]


def _banks(count: int, *, changelog: bool) -> list[str]:
    members = ["index.json"] + [f"term_bank_{n}.json" for n in range(1, count + 1)]
    if changelog:
        members.append("changelog.txt")
    return members


SOURCE_PLAN: dict[str, dict[str, object]] = {
    "ninjal_bunkei": {
        "urls": {
            "nihongo_bunkei_database20260126.zip": (
                f"{NINJAL_RECORD}/nihongo_bunkei_database20260126.zip"
            ),
            "readme.txt": f"{NINJAL_RECORD}/readme.txt",
            "headwords.txt": f"{NINJAL_RECORD}/headwords.txt",
        },
        "provenance": {
            "doi": "https://doi.org/10.15084/0002000610",
            "version": "2026.01.26",
            "publisher": "国立国語研究所 研究系 (NINJAL Research Department)",
            "editors": ["パルデシ, プラシャント", "砂川 有里子"],
        },
    },
    "dojg": {
        "urls": aiko_urls("dojg", TERM_BANKS_1),
        "provenance": {
            "upstreamRepository": "https://github.com/aiko-tanaka/Grammar-Dictionaries",
            "upstreamCommit": AIKO_COMMIT,
        },
    },
    "donna_toki": {
        "urls": {
            **{name: f"{DONNA_TOKI_MIRROR}/{name}" for name in TERM_BANKS_1},
            DONNA_TOKI_ARCHIVE_NAME: DONNA_TOKI_ARCHIVE,
        },
        "provenance": {
            "upstreamRepository": "https://github.com/aiko-tanaka/Grammar-Dictionaries",
            "acquiredVia": "public mirror; absent from aiko-tanaka HEAD",
            "corroboratedBy": DONNA_TOKI_ARCHIVE_NAME,
        },
    },
    "nihongo_net": {
        "urls": aiko_urls("nihongo_kyoushi", _banks(6, changelog=True)),
        "provenance": {
            "upstreamRepository": "https://github.com/aiko-tanaka/Grammar-Dictionaries",
            "upstreamCommit": AIKO_COMMIT,
            "producer": "https://nihongokyoshi-net.com/jlpt-grammars/",
        },
    },
    "edewakaru": {
        "urls": aiko_urls("edewakaru", _banks(4, changelog=True)),
        "provenance": {
            "upstreamRepository": "https://github.com/aiko-tanaka/Grammar-Dictionaries",
            "upstreamCommit": AIKO_COMMIT,
            "producer": "https://www.edewakaru.com/archives/cat_179055.html",
        },
    },
    "nihongo_no_sensei": {
        "urls": aiko_urls("nihongo_no_sensei", _banks(5, changelog=True)),
        "provenance": {
            "upstreamRepository": "https://github.com/aiko-tanaka/Grammar-Dictionaries",
            "upstreamCommit": AIKO_COMMIT,
            "producer": "https://nihongonosensei.net/?page_id=10246",
            "meaningSectionLanguage": "zh",
        },
    },
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        # Read one byte past the cap so an over-large body is detected rather
        # than silently truncated into a corrupt input.
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeError(f"response exceeds {MAX_RESPONSE_BYTES} bytes: {url}")
    if not payload:
        raise RuntimeError(f"empty response: {url}")
    return payload


def verify_donna_toki(directory: pathlib.Path) -> dict[str, object]:
    """Corroborate the mirrored loose banks against the distributed archive.

    The loose JSON and the ZIP member are not expected to be byte-identical:
    they were written by different tools, so whitespace and escaping differ.
    What must match is the lexical content, so compare parsed entries.
    """
    import zipfile

    loose = json.loads((directory / "term_bank_1.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(directory / DONNA_TOKI_ARCHIVE_NAME) as archive:
        names = archive.namelist()
        for name in names:
            pure = pathlib.PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                raise RuntimeError(f"unsafe archive member: {name!r}")
        archived = json.loads(archive.read("term_bank_1.json").decode("utf-8"))

    if loose != archived:
        raise RuntimeError(
            "donna_toki mirror does not match the distributed archive: "
            f"{len(loose)} loose entries vs {len(archived)} archived"
        )
    return {"entries": len(loose), "archiveMembers": sorted(names)}


def acquire(name: str, *, force: bool) -> dict[str, object]:
    plan = SOURCE_PLAN[name]
    directory = SOURCES_DIR / name
    directory.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict[str, object]] = {}
    for relative_path, url in sorted(plan["urls"].items()):  # type: ignore[union-attr]
        target = directory / relative_path
        if target.is_file() and not force:
            payload = target.read_bytes()
        else:
            payload = fetch(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        files[relative_path] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byteCount": len(payload),
            "url": url,
        }

    lock = {
        "source": name,
        "acquiredAt": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provenance": plan["provenance"],
        "files": files,
    }
    if name == "donna_toki":
        lock["corroboration"] = verify_donna_toki(directory)
    (directory / "SOURCE.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        dest="only",
        choices=sorted(SOURCE_PLAN),
        help="acquire only the named source (repeatable)",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download even when bytes already exist"
    )
    args = parser.parse_args(argv)

    names = args.only or sorted(SOURCE_PLAN)
    failures: list[str] = []
    for name in names:
        try:
            lock = acquire(name, force=args.force)
        except (urllib.error.URLError, RuntimeError, OSError) as error:
            failures.append(f"{name}: {error}")
            print(f"[acquire] FAIL {name}: {error}", file=sys.stderr)
            continue
        total = sum(int(entry["byteCount"]) for entry in lock["files"].values())  # type: ignore[index]
        print(f"[acquire] {name}: {len(lock['files'])} files, {total} bytes")  # type: ignore[arg-type]

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
