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

from .jsonio import MalformedPayload, load_json
from .package import MEDIA_DIR

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

#: Native kanji banks are forbidden: Yomitan routes kanji clicks to a fixed
#: unstyleable renderer that would supersede the structured card.
FORBIDDEN_BANK = re.compile(r"^(?:kanji_bank|kanji_meta_bank)_[1-9][0-9]*\.json$")


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / name
    if not path.is_file():
        raise MalformedPayload(f"pinned schema is missing: {path}")
    return load_json(path.read_text(encoding="utf-8"))


def validate_zip(zip_path: str | pathlib.Path) -> list[str]:
    """Validate one built ZIP; return the list of failures (empty means pass)."""
    failures: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        name_set = set(names)

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
    return failures


def _check(payload: Any, schema_name: str, member: str) -> list[str]:
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


__all__ = ["SCHEMA_DIR", "load_schema", "validate_zip"]
