"""Read ``harness/configs/parser_preference.yaml``: which parse of a URL the build uses.

Mongo ``parsed_documents`` is keyed by ``(url, parser, parser_version)``, so one URL can
have several clean rows. The file lists, per content type, the parsers in order of
preference. An entry ``name`` matches every version of a parser; ``name@version``
matches that version only.

The version form exists because the 58,121 PDF rows that the graph was embedded from
carry ``parser: pymupdf4llm, parser_version: legacy``, and a new parse with the
installed library writes ``(url, pymupdf4llm, 1.27.2.3)``. With names alone, "preferred
parser, then newest" would let the new row replace the legacy text. Writing
``pymupdf4llm@legacy`` first keeps it (decision D,
``docs/pm/decisions/2026-11-25_legacy-parser-name.md``).

The reader is pure: a path in, a mapping out. Selection lives in
``harness.indexing.ingest``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

import yaml

PREFERENCE_PATH = Path(__file__).resolve().parents[1] / "configs" / "parser_preference.yaml"


class PreferenceEntry(NamedTuple):
    """One entry of the file: a parser name and, optionally, one version of it."""

    parser: str
    version: str | None = None

    def matches(self, parser: str | None, parser_version: str | None) -> bool:
        """True when a row with this ``parser`` and ``parser_version`` matches the entry."""
        if parser != self.parser:
            return False
        return self.version is None or parser_version == self.version


def parse_entry(text: str) -> PreferenceEntry:
    """``'pymupdf4llm'`` → any version; ``'pymupdf4llm@legacy'`` → that version only."""
    raw = str(text).strip()
    name, sep, version = raw.partition("@")
    name, version = name.strip(), version.strip()
    if not name or (sep and not version):
        raise ValueError(f"invalid parser preference entry {text!r}: expected 'name' or 'name@version'")
    return PreferenceEntry(name, version if sep else None)


def parse_preference(raw: Any, *, source: str = "parser preference") -> dict[str, list[PreferenceEntry]]:
    """Validate the loaded YAML: a mapping of content type to a list of entries."""
    if not isinstance(raw, dict):
        raise ValueError(f"{source} must be a mapping of content type to a list; got {type(raw).__name__}")
    preference: dict[str, list[PreferenceEntry]] = {}
    for content_type, entries in raw.items():
        if not isinstance(entries, list):
            raise ValueError(f"{source}: {content_type!r} must map to a list; got {type(entries).__name__}")
        preference[str(content_type).strip().lower()] = [parse_entry(e) for e in entries]
    return preference


def load_parser_preference(path: Path | None = None) -> dict[str, list[PreferenceEntry]]:
    """Load the preference file (default: the shipped ``parser_preference.yaml``)."""
    path = path or PREFERENCE_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_preference(raw, source=str(path))
