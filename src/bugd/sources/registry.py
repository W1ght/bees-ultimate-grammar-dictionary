"""Source registry.

Later cards add one module per source and register it here. The registry is the
only place the pipeline learns which sources exist, so `extract` and `merge`
never need a hard-coded source list.
"""

from __future__ import annotations

import importlib
import pathlib
import pkgutil

from .base import Extractor

_REGISTRY: dict[str, type[Extractor]] = {}

#: Modules in this package that are infrastructure rather than a source. Every
#: other module is a source and must register an extractor when imported.
_NON_SOURCE_MODULES = frozenset({"base", "registry"})


def register_extractor(cls: type[Extractor]) -> type[Extractor]:
    """Register one extractor class; usable as a decorator."""
    if not issubclass(cls, Extractor):
        raise TypeError(f"{cls!r} is not an Extractor subclass")
    if not cls.name:
        raise ValueError(f"{cls.__name__} does not declare a source name")
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"source name {cls.name!r} is already registered by {existing.__name__}")
    _REGISTRY[cls.name] = cls
    return cls


def load_source_modules() -> list[str]:
    """Import every source module in this package so each one registers itself.

    The registry is populated by import side effect: a module's
    `@register_extractor` decorator only runs once that module is imported. Until
    this existed nothing in the shipped code ever imported the concrete source
    modules, so `all_extractors()` returned an empty list in a complete checkout
    and `bugd.cli extract` reported `{"sources": {}, "total": 0}` and exited 0 --
    a silent no-op build. Only throwaway driver scripts that hard-coded
    `import bugd.sources.dojg` produced the real artifacts, which is exactly the
    hard-coded source list the registry seam exists to avoid.

    Discovery walks the package rather than naming modules, so adding a source
    stays a one-file change. Import errors are not swallowed: a source that
    cannot be imported is a build defect and must fail loudly here rather than
    silently shrink the dictionary.
    """
    imported: list[str] = []
    package_path = [str(pathlib.Path(__file__).resolve().parent)]
    for info in sorted(pkgutil.iter_modules(package_path), key=lambda i: i.name):
        if info.ispkg or info.name.startswith("_") or info.name in _NON_SOURCE_MODULES:
            continue
        importlib.import_module(f"{__package__}.{info.name}")
        imported.append(info.name)
    return imported


def get_extractor(name: str) -> type[Extractor]:
    load_source_modules()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown source: {name!r} (known: {', '.join(source_names()) or 'none'})")


def source_names() -> list[str]:
    load_source_modules()
    return sorted(_REGISTRY)


def all_extractors() -> list[type[Extractor]]:
    return [_REGISTRY[name] for name in source_names()]


def discover_extractors() -> list[str]:
    """Import every sibling source module so its `@register_extractor` runs.

    The registry is populated as a side effect of importing each source module,
    but nothing imports them for the pipeline -- `from .sources import
    all_extractors` only executes `__init__`, which does not. So `run_extract`
    saw an empty registry and wrote zero artifacts, and a build silently fell
    back to whatever stale `data/extracted/*.json` was on disk. Walking the
    package here makes the documented `extract` stage actually run every source,
    which is what keeps a re-extract reproducible instead of packaging cached
    pre-fix text.

    A module that fails to import (an in-progress source that is not part of this
    build) is skipped with its name recorded rather than aborting discovery, so
    one broken scratch module cannot take the whole pipeline down.
    """
    import importlib
    import pkgutil

    from . import __path__ as _package_path

    skipped: list[str] = []
    for module in pkgutil.iter_modules(_package_path):
        if module.name in {"base", "registry", "community", "yomitan_bank"}:
            # base/registry are infrastructure; community and yomitan_bank are
            # shared base classes that deliberately do not self-register.
            continue
        try:
            importlib.import_module(f"{__name__.rsplit('.', 1)[0]}.{module.name}")
        except Exception:  # pragma: no cover - a broken in-progress source module
            skipped.append(module.name)
    return skipped


__all__ = [
    "register_extractor",
    "load_source_modules",
    "get_extractor",
    "source_names",
    "all_extractors",
    "discover_extractors",
]
