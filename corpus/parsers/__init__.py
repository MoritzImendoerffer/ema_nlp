"""Parsers — pluggable layer that turns raw bytes/HTML into ParsedDocument.

Each parser module under this package exposes a class implementing the Parser
protocol (added in MIGR-004) and writes its output to Mongo via
:func:`corpus.sources.parsed_documents.write_parsed_document`.

The base types (`ParsedDocument`, later the `Parser` protocol) live in
:mod:`corpus.parsers.base`.
"""

from corpus.parsers.base import ParsedDocument

__all__ = ["ParsedDocument"]
