"""Exporter registry — name -> Exporter class (config-selectable, extensible).

Mirrors the tool-registry idiom (``harness/tools/registry.py``): a decorator
with a duplicate guard, sorted listing, and a strict lookup whose error names
the available exporters. Extending the export surface = subclass
:class:`harness.export.base.Exporter` and register it::

    from harness.export import Exporter, register_exporter

    @register_exporter("confluence")
    class ConfluenceExporter(Exporter):
        ...

then add the name to ``configs/export/*.yaml`` ``formats:``.
"""

from __future__ import annotations

from collections.abc import Callable

_EXPORTER_REGISTRY: dict[str, type] = {}


def register_exporter(name: str) -> Callable[[type], type]:
    """Register an :class:`Exporter` subclass under ``name`` (decorator)."""

    def _decorator(cls: type) -> type:
        if name in _EXPORTER_REGISTRY:
            raise ValueError(f"Exporter {name!r} is already registered")
        _EXPORTER_REGISTRY[name] = cls
        return cls

    return _decorator


def list_exporters() -> list[str]:
    """Sorted names of registered exporters."""
    return sorted(_EXPORTER_REGISTRY)


def get_exporter(name: str):
    """Instantiate the exporter registered under ``name``.

    Unknown names are a hard config error (the export config must never claim a
    format that cannot run).
    """
    if name not in _EXPORTER_REGISTRY:
        available = ", ".join(list_exporters()) or "(none registered)"
        raise ValueError(f"Unknown exporter {name!r}. Available: {available}")
    return _EXPORTER_REGISTRY[name]()
