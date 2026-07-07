"""Config-driven, subclass-extensible export of answered turns (MD/HTML).

- ``ExportBundle``  — one turn's data; ``to_dict()`` is the interchange format
- ``Exporter``      — the format contract; subclass + ``@register_exporter``
- ``export_turn``   — render a bundle in the configured (or given) formats
- config            — ``configs/export/<name>.yaml`` via the ``$EMA_CONFIG_DIR``
                      search path; unknown keys/formats are hard errors

See ``docs/CITATIONS.md``.
"""

from harness.export.base import Exporter, ExportOptions, load_export_options
from harness.export.bundle import ExportBundle
from harness.export.html import HtmlExporter
from harness.export.markdown import MarkdownExporter
from harness.export.registry import get_exporter, list_exporters, register_exporter


def export_turn(
    bundle: ExportBundle,
    formats: list[str] | None = None,
    options: ExportOptions | None = None,
) -> list[tuple[str, str, str]]:
    """Render ``bundle`` in each format; returns ``[(filename, mime, content), ...]``."""
    options = options or load_export_options()
    out: list[tuple[str, str, str]] = []
    for name in formats or options.formats:
        exporter = get_exporter(name)
        out.append((exporter.filename(bundle, options), exporter.mime, exporter.render(bundle, options)))
    return out


__all__ = [
    "ExportBundle",
    "Exporter",
    "ExportOptions",
    "HtmlExporter",
    "MarkdownExporter",
    "export_turn",
    "get_exporter",
    "list_exporters",
    "load_export_options",
    "register_exporter",
]
