"""Exporter contract + config-driven export options.

An :class:`Exporter` turns one :class:`~harness.export.bundle.ExportBundle`
into a downloadable document. Options come from ``configs/export/<name>.yaml``
(built-in ``harness/configs/export/``, overridable via ``$EMA_CONFIG_DIR/export/``
— the same search path recipes use) and are validated hard: an unknown key or an
unregistered format is a config error, never a silent default (F10 precedent).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from harness.config_paths import find_config
from harness.export.registry import list_exporters

if TYPE_CHECKING:  # pragma: no cover
    from harness.export.bundle import ExportBundle

_KNOWN_KEYS = {
    "formats",
    "include_config",
    "include_judge",
    "include_full_passages",
    "include_trace_link",
    "include_chain_output",
    "include_chain_graph",
    "filename_template",
}


@dataclass
class ExportOptions:
    """Resolved export configuration (one per ``configs/export/*.yaml``)."""

    formats: list[str] = field(default_factory=lambda: ["markdown", "html"])
    include_config: bool = True
    include_judge: bool = True
    include_full_passages: bool = True
    include_trace_link: bool = True
    include_chain_output: bool = False  # chain_html: raw tool output per step
    include_chain_graph: bool = True  # chain_html: mini subgraph of docs touched
    filename_template: str = "ema_answer_{msg_num}_{run8}"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ExportOptions:
        d = d or {}
        unknown = set(d) - _KNOWN_KEYS
        if unknown:
            raise ValueError(
                f"Unknown export option(s) {sorted(unknown)}; known: {sorted(_KNOWN_KEYS)}"
            )
        formats = [str(f) for f in (d.get("formats") or ["markdown", "html"])]
        registered = set(list_exporters())
        bad = [f for f in formats if f not in registered]
        if bad:
            raise ValueError(
                f"export.formats names unregistered exporter(s) {bad}; "
                f"registered: {sorted(registered)}"
            )
        return cls(
            formats=formats,
            include_config=bool(d.get("include_config", True)),
            include_judge=bool(d.get("include_judge", True)),
            include_full_passages=bool(d.get("include_full_passages", True)),
            include_trace_link=bool(d.get("include_trace_link", True)),
            include_chain_output=bool(d.get("include_chain_output", False)),
            include_chain_graph=bool(d.get("include_chain_graph", True)),
            filename_template=str(d.get("filename_template", "ema_answer_{msg_num}_{run8}")),
        )


def load_export_options(name: str = "default") -> ExportOptions:
    """Load ``export/<name>.yaml`` through the config search path."""
    path = find_config("export", f"{name}.yaml")
    if path is None:
        raise FileNotFoundError(
            f"Export config not found: {name!r} (searched $EMA_CONFIG_DIR/export "
            "and the built-in export/)"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ExportOptions.from_dict(raw.get("export", raw))


class Exporter(ABC):
    """One export format. Subclass + ``@register_exporter(name)`` to extend."""

    name: str = ""
    file_extension: str = ""
    mime: str = "application/octet-stream"

    @abstractmethod
    def render(self, bundle: ExportBundle, options: ExportOptions) -> str:
        """Render the bundle to the format's full document text."""

    def filename(self, bundle: ExportBundle, options: ExportOptions) -> str:
        stem = options.filename_template.format(
            msg_num=bundle.msg_num, run8=(bundle.run_id or "run")[:8], recipe=bundle.recipe_name
        )
        return f"{stem}.{self.file_extension}"
