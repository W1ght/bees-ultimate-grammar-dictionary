"""Per-source extractors and normalizers.

One module per source. Each module exposes an `Extractor` subclass and registers
it in `bugd.sources.registry`. No source logic lives outside this package: the
merge and bank stages only ever see `GrammarPoint` records.

`data/sources/` convention
--------------------------
Raw acquired inputs live under `data/sources/<source-name>/`, gitignored and
regenerable. Each source directory holds the untouched bytes the extractor
consumed plus a `SOURCE.lock.json` recording, for every consumed file:

    {"path": ..., "sha256": ..., "byteCount": ..., "acquiredAt": ...}

The lock is what makes a build reproducible: extractors read only files listed
in the lock and fail closed when a digest does not match.
"""

from __future__ import annotations

from .base import Extractor, ExtractResult, SourceLockError, load_source_lock
from .registry import all_extractors, get_extractor, register_extractor, source_names

__all__ = [
    "Extractor",
    "ExtractResult",
    "SourceLockError",
    "load_source_lock",
    "all_extractors",
    "get_extractor",
    "register_extractor",
    "source_names",
]
