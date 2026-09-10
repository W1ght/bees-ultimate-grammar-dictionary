"""Packaging: banks + media -> one reproducible Yomitan ZIP.

Reproducibility rules enforced here:

* fixed member timestamps and permissions, so identical content yields identical
  archive bytes;
* deterministic member order (sorted);
* bank JSON, `index.json`, and `styles.css` at the ZIP root —
  Yomitan requires bank JSON at the root; only media may live in a subfolder.
"""

from __future__ import annotations

import io
import pathlib
import stat
import zipfile

from .jsonio import MalformedPayload, dump_json

#: Fixed ZIP member timestamp (the DOS epoch) for byte-reproducible archives.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

#: Media members are the only permitted non-root paths.
MEDIA_DIR = "media"


def _member(name: str, data: bytes | str) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(filename=name, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.create_system = 3  # unix
    if isinstance(data, str):
        data = data.encode("utf-8")
    return info, data


def build_zip(members: dict[str, bytes | str]) -> bytes:
    """Pack `members` (member name -> bytes/text) into a reproducible ZIP."""
    for name in members:
        pure = pathlib.PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or pure.is_absolute()
            or ".." in pure.parts
            or "." in pure.parts
            or str(pure) != name
        ):
            raise MalformedPayload(f"unsafe ZIP member name: {name!r}")
        if "/" in name and not name.startswith(f"{MEDIA_DIR}/"):
            raise MalformedPayload(
                f"non-root member outside {MEDIA_DIR}/: {name!r} "
                "(Yomitan requires bank JSON at the ZIP root)"
            )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(members):
            info, data = _member(name, members[name])
            archive.writestr(info, data)
    return buffer.getvalue()


def package_members(
    *,
    index: dict,
    banks: dict[str, list],
    styles_css: str,
    tag_bank: list | None = None,
    media: dict[str, bytes] | None = None,
    extra: dict[str, bytes | str] | None = None,
) -> dict[str, bytes | str]:
    """Assemble the complete member map for the dictionary ZIP."""
    members: dict[str, bytes | str] = {
        "index.json": dump_json(index),
        "styles.css": styles_css,
    }
    for name, bank in banks.items():
        members[name] = dump_json(bank)
    if tag_bank:
        members["tag_bank_1.json"] = dump_json(tag_bank)
    for name, payload in (media or {}).items():
        members[f"{MEDIA_DIR}/{name}"] = payload
    members.update(extra or {})
    return members


__all__ = ["ZIP_DATE", "MEDIA_DIR", "build_zip", "package_members"]
