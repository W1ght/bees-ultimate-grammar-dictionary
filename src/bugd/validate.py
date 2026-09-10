"""Schema validation of a built ZIP against the pinned official Yomitan schemas.

Python-side gate used by `make validate` / the test suite. `scripts/validate_yomitan.mjs`
is the independent Node/ajv cross-check of the same artifact — two implementations
against the same pinned schema bytes.
"""

from __future__ import annotations

import pathlib
import re
import zipfile
from typing import Any

import jsonschema

try:  # optional accelerator; see _compiled_validator for why it matters
    import fastjsonschema
except ImportError:  # pragma: no cover - exercised by the no-accelerator path
    fastjsonschema = None

from .jsonio import MalformedPayload, load_json
from .package import MEDIA_DIR

#: Compiled-validator cache keyed by pinned schema file name. Compiling the
#: term-bank schema is cheap (~0.06s) but happens once per bank member otherwise.
_COMPILED_CACHE: dict[str, Any] = {}

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"

SCHEMA_FOR_MEMBER = {"index.json": "dictionary-index-schema.json"}

BANK_GROUPS = (
    (re.compile(r"^term_bank_([1-9][0-9]*)\.json$"), "dictionary-term-bank-v3-schema.json"),
    (
        re.compile(r"^term_meta_bank_([1-9][0-9]*)\.json$"),
        "dictionary-term-meta-bank-v3-schema.json",
    ),
    (re.compile(r"^tag_bank_([1-9][0-9]*)\.json$"), "dictionary-tag-bank-v3-schema.json"),
)

REQUIRED_ROOT_MEMBERS = ("index.json", "styles.css")

#: Non-bank root members this dictionary is allowed to ship. Yomitan ignores them
#: at import; the allowance exists so a NOTICE or credits file can travel with the
#: archive without tripping the unknown-member gate.
ALLOWED_EXTRA_MEMBERS = frozenset({"LICENSE", "NOTICE", "ATTRIBUTION.md"})

#: Native kanji banks are forbidden: Yomitan routes kanji clicks to a fixed
#: unstyleable renderer that would supersede the structured card.
FORBIDDEN_BANK = re.compile(r"^(?:kanji_bank|kanji_meta_bank)_[1-9][0-9]*\.json$")


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / name
    if not path.is_file():
        raise MalformedPayload(f"pinned schema is missing: {path}")
    return load_json(path.read_text(encoding="utf-8"))


def term_entry_count(zip_path: str | pathlib.Path) -> int:
    """Count term entries across every contiguous term bank in a built ZIP.

    This is the number the packaging stage prints and the non-empty gate compares
    against: the count of records Yomitan will actually import, read back from
    the artifact rather than from the in-memory corpus that produced it.
    """
    pattern = BANK_GROUPS[0][0]
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not pattern.match(name):
                continue
            payload = load_json(archive.read(name).decode("utf-8"))
            if not isinstance(payload, list):
                raise MalformedPayload(f"term bank is not a JSON array: {name}")
            total += len(payload)
    return total


def validate_zip(
    zip_path: str | pathlib.Path, *, require_entries: bool = False
) -> list[str]:
    """Validate one built ZIP; return the list of failures (empty means pass).

    Schema validation is always fail-closed: any member that does not match its
    pinned official Yomitan schema is a failure. `require_entries` adds the
    release gate — an importable dictionary must actually carry term entries, so
    a structurally valid but empty archive is refused rather than published.
    """
    failures: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        name_set = set(names)

        if len(names) != len(name_set):
            failures.append("archive contains duplicate member names")

        for name in names:
            if "/" in name and not name.startswith(f"{MEDIA_DIR}/"):
                failures.append(f"unexpected non-root member: {name}")
            if FORBIDDEN_BANK.match(name):
                failures.append(f"forbidden native kanji bank present: {name}")
        for required in REQUIRED_ROOT_MEMBERS:
            if required not in name_set:
                failures.append(f"missing expected member: {required}")

        parsed: dict[str, Any] = {}
        for member, schema_name in SCHEMA_FOR_MEMBER.items():
            if member not in name_set:
                continue
            payload = load_json(archive.read(member).decode("utf-8"))
            parsed[member] = payload
            failures.extend(_check(payload, schema_name, member))

        for pattern, schema_name in BANK_GROUPS:
            numbered = sorted(
                (int(match.group(1)), name)
                for name in names
                if (match := pattern.match(name))
            )
            for position, (number, name) in enumerate(numbered, start=1):
                if number != position:
                    failures.append(f"bank members are not contiguous from 1: {name}")
                payload = load_json(archive.read(name).decode("utf-8"))
                parsed[name] = payload
                failures.extend(_check(payload, schema_name, name))

        failures.extend(_check_media_references(parsed, name_set))
        failures.extend(_check_unknown_members(names))

        if require_entries:
            entries = sum(
                len(payload)
                for name, payload in parsed.items()
                if name.startswith("term_bank_") and isinstance(payload, list)
            )
            if entries == 0:
                failures.append(
                    "no term entries: an importable dictionary must carry at least one "
                    "term bank entry (refusing to package an empty dictionary)"
                )
    return failures


def _check_unknown_members(names: list[str]) -> list[str]:
    """Refuse members Yomitan would ignore, so nothing ships unnoticed.

    Yomitan silently skips archive members it does not recognise. A stray file at
    the ZIP root is therefore invisible at import time but still shipped to
    users, so packaging fails closed on it instead.
    """
    known = set(REQUIRED_ROOT_MEMBERS) | set(SCHEMA_FOR_MEMBER)
    failures = []
    for name in names:
        if name.startswith(f"{MEDIA_DIR}/") or name in known or name in ALLOWED_EXTRA_MEMBERS:
            continue
        if any(pattern.match(name) for pattern, _ in BANK_GROUPS):
            continue
        failures.append(f"unrecognised archive member Yomitan would ignore: {name}")
    return failures


def _compiled_validator(schema_name: str):
    """A compiled validator for a pinned schema, or None when unavailable.

    Pure-Python `jsonschema` walks the term-bank schema's deeply recursive
    structured-content `oneOf` for every node: profiling one real card measured
    ~8M function calls and ~2s PER ENTRY, i.e. well over an hour for a 2,419-entry
    corpus, which makes the gate unusable at full scale. `fastjsonschema`
    generates straight-line Python for the same pinned schema bytes and validates
    1,000 entries in ~3s.

    This is an accelerator, not a policy change: the schema, the failure
    condition, and the fail-closed behaviour are identical, and both validators
    were checked to reject the same malformed payloads (nested `p`, non-integer
    sequence, short entry, non-array glossary, non-array bank). When the
    accelerator is not installed the original validator is used, so the gate
    never silently weakens — it only gets slower.
    """
    if fastjsonschema is None:
        return None
    compiled = _COMPILED_CACHE.get(schema_name)
    if compiled is None:
        compiled = fastjsonschema.compile(load_schema(schema_name))
        _COMPILED_CACHE[schema_name] = compiled
    return compiled


def _check(payload: Any, schema_name: str, member: str) -> list[str]:
    compiled = _compiled_validator(schema_name)
    if compiled is not None:
        try:
            compiled(payload)
        except fastjsonschema.JsonSchemaException as error:  # type: ignore[union-attr]
            return [f"{member} does not match {schema_name}: {error.message}"]
        return []
    validator = jsonschema.Draft7Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    return [
        f"{member} does not match {schema_name}: {error.json_path} {error.message}"
        for error in errors[:5]
    ]


def _check_media_references(parsed: dict[str, Any], name_set: set[str]) -> list[str]:
    """Every structured-content media path must resolve to a packaged member."""
    referenced: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("tag") == "img" and isinstance(node.get("path"), str):
                referenced.add(node["path"])
            for value in node.values():
                walk(value)

    for member, payload in parsed.items():
        if member.startswith("term_bank_"):
            walk(payload)
    return [f"dangling media reference: {path}" for path in sorted(referenced - name_set)]


__all__ = [
    "SCHEMA_DIR",
    "ALLOWED_EXTRA_MEMBERS",
    "load_schema",
    "validate_zip",
    "term_entry_count",
]
