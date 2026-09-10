"""Acquire the Yokubi lesson corpus into `data/sources/yokubi/`.

Acquisition properties:

* the upstream git repository is the source of truth, pinned to an exact commit;
  no rendered-site scraping happens, so the website's presentation terms are
  never engaged and mdBook preprocessing never sits between us and the prose;
* it is content-addressed: the requested revision is resolved to a full commit
  sha, every consumed blob is hashed over the exact bytes stored, and a
  re-acquisition of the same commit reproduces the same lock;
* it is bounded: only `src/**.md`, `LICENSE`, and `book.toml` are stored, with a
  per-file and total byte ceiling, and archive members are path-validated before
  extraction;
* it is fail-closed: `SOURCE.lock.json` is written only after every expected
  member has been stored, and a partial corpus raises instead of silently
  locking a subset.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import pathlib
import shutil
import sys
import tarfile
import urllib.error
import urllib.request

REPO = "Morgawr/yokubi"
DEFAULT_REVISION = "b1c0938b0bda58e20c6ccd21288b46711b438239"
USER_AGENT = "bees-ultimate-grammar-dictionary/1.0 (local Yomitan dictionary build)"

DEFAULT_DIR = pathlib.Path("data/sources/yokubi")
LOCK_NAME = "SOURCE.lock.json"

# Members worth storing: the lesson prose, the book manifest that documents
# mdBook's furigana preprocessor, and the two upstream files the lock pins
# alongside them (LICENSE, src/Credits.md) so a re-acquisition reproduces the
# same 78-file manifest.
WANTED_PREFIXES = ("src/",)
WANTED_EXACT = ("LICENSE", "book.toml")
WANTED_SUFFIXES = (".md",)

# Archive-expansion ceilings. The whole repository is ~236 KiB, so these bound a
# hostile or corrupted tarball by a wide margin without constraining real growth.
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 5000

def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code} for {url}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SystemExit(f"cannot reach {url}: {error}") from error


def resolve_commit(revision: str) -> dict:
    """Resolve a revision to an exact commit, so the lock is content-addressed."""
    payload = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{revision}"))
    sha = payload.get("sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise SystemExit(f"could not resolve {revision!r} to a commit sha")
    committed = (payload.get("commit") or {}).get("committer") or {}
    return {"sha": sha, "committedAt": committed.get("date")}


def wanted(name: str) -> bool:
    if name in WANTED_EXACT:
        return True
    return name.startswith(WANTED_PREFIXES) and name.endswith(WANTED_SUFFIXES)


def safe_relative(name: str) -> str:
    """Reject absolute, traversing, or backslash member paths before extraction."""
    if not name or "\\" in name or name.startswith("/"):
        raise SystemExit(f"unsafe archive member path: {name!r}")
    pure = pathlib.PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise SystemExit(f"unsafe archive member path: {name!r}")
    return str(pure)


def extract(tarball: bytes, target: pathlib.Path) -> dict[str, bytes]:
    """Extract the wanted members from the pinned tarball, bounded and validated."""
    members: dict[str, bytes] = {}
    total = 0
    seen = 0
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for member in archive:
            seen += 1
            if seen > MAX_MEMBERS:
                raise SystemExit(f"archive exceeds {MAX_MEMBERS} members")
            if member.issym() or member.islnk():
                raise SystemExit(f"archive contains a link member: {member.name!r}")
            if not member.isfile():
                continue
            # GitHub tarballs nest everything under `<repo>-<sha>/`.
            relative = safe_relative(member.name).partition("/")[2]
            if not relative or not wanted(relative):
                continue
            if member.size > MAX_MEMBER_BYTES:
                raise SystemExit(f"member {relative!r} exceeds {MAX_MEMBER_BYTES} bytes")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise SystemExit(f"archive expansion exceeds {MAX_TOTAL_BYTES} bytes")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"cannot read member {relative!r}")
            members[relative] = handle.read()

    if not members:
        raise SystemExit("archive contained none of the expected members")
    for required in ("src/SUMMARY.md", "src/Credits.md", "LICENSE"):
        if required not in members:
            raise SystemExit(f"archive is missing the required member {required!r}")

    for relative, raw in sorted(members.items()):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    return members


def acquire(target: pathlib.Path, *, revision: str, force: bool) -> dict:
    commit = resolve_commit(revision)
    sha = commit["sha"]

    if target.exists() and force:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    tarball = fetch(f"https://codeload.github.com/{REPO}/tar.gz/{sha}")
    members = extract(tarball, target)

    files: dict[str, dict] = {}
    for relative, raw in sorted(members.items()):
        stored = (target / relative).read_bytes()
        if stored != raw:
            raise SystemExit(f"stored bytes for {relative!r} do not match the archive")
        files[relative] = {
            "sha256": hashlib.sha256(stored).hexdigest(),
            "byteCount": len(stored),
        }

    lesson_count = sum(
        1 for name in files if name.startswith("src/") and "/Lesson" in name
    )
    lock = {
        "source": "yokubi",
        "acquiredAt": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "repository": f"https://github.com/{REPO}",
        "revision": sha,
        "revisionCommittedAt": commit["committedAt"],
        "archive": f"https://codeload.github.com/{REPO}/tar.gz/{sha}",
        "archiveSha256": hashlib.sha256(tarball).hexdigest(),
        "files": files,
    }
    (target / LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {
        "revision": sha,
        "lockedFiles": len(files),
        "lessonFiles": lesson_count,
        "totalBytes": sum(entry["byteCount"] for entry in files.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire the Yokubi lesson corpus")
    parser.add_argument("--target", type=pathlib.Path, default=DEFAULT_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument(
        "--force", action="store_true", help="remove the target directory first"
    )
    args = parser.parse_args(argv)
    print(json.dumps(acquire(args.target, revision=args.revision, force=args.force)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
