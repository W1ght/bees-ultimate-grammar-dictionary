"""Source registry.

Later cards add one module per source and register it here. The registry is the
only place the pipeline learns which sources exist, so `extract` and `merge`
never need a hard-coded source list.
"""

from __future__ import annotations

from .base import Extractor

_REGISTRY: dict[str, type[Extractor]] = {}


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


def get_extractor(name: str) -> type[Extractor]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown source: {name!r} (known: {', '.join(source_names()) or 'none'})")


def source_names() -> list[str]:
    return sorted(_REGISTRY)


def all_extractors() -> list[type[Extractor]]:
    return [_REGISTRY[name] for name in source_names()]


__all__ = ["register_extractor", "get_extractor", "source_names", "all_extractors"]
