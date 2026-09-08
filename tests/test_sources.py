"""Source registry + digest-locked source reading."""

from __future__ import annotations

import hashlib

import pytest

from bugd.jsonio import dump_json
from bugd.sources import Extractor, ExtractResult, SourceLockError, load_source_lock
from bugd.sources.base import SOURCE_LOCK_NAME
from bugd.sources.registry import register_extractor, source_names


class _Fixture(Extractor):
    name = "unit-fixture"
    label = "Unit Fixture"


def _write_source(tmp_path, payload: bytes, *, digest=None, byte_count=None):
    directory = tmp_path / "unit-fixture"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.txt").write_bytes(payload)
    lock = {
        "source": "unit-fixture",
        "files": {
            "input.txt": {
                "sha256": digest or hashlib.sha256(payload).hexdigest(),
                "byteCount": byte_count if byte_count is not None else len(payload),
            }
        },
    }
    (directory / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    return directory


def test_extract_is_not_implemented_at_scaffold_time(tmp_path):
    with pytest.raises(NotImplementedError):
        _Fixture(tmp_path).extract()


def test_read_locked_bytes_accepts_matching_digest(tmp_path):
    directory = _write_source(tmp_path, b"hello")
    assert _Fixture(directory).read_locked_bytes("input.txt") == b"hello"


def test_read_locked_bytes_fails_closed_on_digest_mismatch(tmp_path):
    directory = _write_source(tmp_path, b"hello", digest="0" * 64)
    with pytest.raises(SourceLockError, match="digest mismatch"):
        _Fixture(directory).read_locked_bytes("input.txt")


def test_read_locked_bytes_fails_closed_on_byte_count_mismatch(tmp_path):
    directory = _write_source(tmp_path, b"hello", byte_count=99)
    with pytest.raises(SourceLockError, match="byte count"):
        _Fixture(directory).read_locked_bytes("input.txt")


def test_unlocked_file_is_refused(tmp_path):
    directory = _write_source(tmp_path, b"hello")
    (directory / "extra.txt").write_bytes(b"not locked")
    with pytest.raises(SourceLockError, match="not listed"):
        _Fixture(directory).read_locked_bytes("extra.txt")


def test_missing_lock_is_an_error(tmp_path):
    with pytest.raises(SourceLockError, match="missing source lock"):
        load_source_lock(tmp_path)


@pytest.mark.parametrize("unsafe", ["/abs.txt", "../escape.txt", "a\\b.txt", "./here.txt"])
def test_unsafe_locked_paths_are_refused(tmp_path, unsafe):
    lock = {"source": "x", "files": {unsafe: {"sha256": "0" * 64, "byteCount": 1}}}
    (tmp_path / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    with pytest.raises(SourceLockError, match="unsafe locked path"):
        load_source_lock(tmp_path)


@pytest.mark.parametrize(
    "entry",
    [
        {"byteCount": 1},
        {"sha256": "short", "byteCount": 1},
        {"sha256": "0" * 64},
        {"sha256": "0" * 64, "byteCount": -1},
        {"sha256": "0" * 64, "byteCount": True},
    ],
)
def test_malformed_lock_entries_are_refused(tmp_path, entry):
    lock = {"source": "x", "files": {"input.txt": entry}}
    (tmp_path / SOURCE_LOCK_NAME).write_text(dump_json(lock), encoding="utf-8")
    with pytest.raises(SourceLockError):
        load_source_lock(tmp_path)


def test_extract_result_rejects_misattributed_points(sample_point):
    with pytest.raises(Exception):
        ExtractResult(source="other", points=[sample_point])


def test_registry_rejects_duplicate_names():
    class First(Extractor):
        name = "dupe-check"

    class Second(Extractor):
        name = "dupe-check"

    register_extractor(First)
    assert "dupe-check" in source_names()
    with pytest.raises(ValueError, match="already registered"):
        register_extractor(Second)


def test_registry_rejects_unnamed_extractor():
    class Unnamed(Extractor):
        pass

    with pytest.raises(ValueError, match="does not declare a source name"):
        register_extractor(Unnamed)


def test_no_sources_registered_yet_by_import():
    """The scaffold ships no source logic; later cards register real sources."""
    import importlib

    import bugd.sources.registry as registry

    fresh = importlib.reload(registry)
    assert fresh.source_names() == []
