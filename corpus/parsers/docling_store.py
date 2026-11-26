"""Where a Docling parse is stored, and under which names (backlog row 17).

Pure Python: no Docling import, so the retrieval environment (``.venv``) and the gate can
use and test it. The parse environment imports it too.

Per PDF one folder::

    <parsed root>/<doc-id>/docling@<options hash, 8 hex>/
        doc.raw.json   Docling's document as the parser returned it, without images
        doc.json       the same after post-processing (rebuilt from doc.raw.json at any time)
        run.json       the run record: source hash, versions, model revisions, options, counts

The document id is ``<slug>_<hash12>``: the last part of the URL, cut to 40 characters,
and the first 12 hex characters of the SHA-256 of the PDF bytes. doctool uses 6 hex
characters (``src/dw/ids.py:124-131``); for about 66,000 PDFs that gave an expected 4%
chance of two different PDFs sharing a folder. Two PDFs with the same bytes share one
folder on purpose, and are parsed once.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PARSER_NAME = "docling"
RAW_FILE = "doc.raw.json"
DOC_FILE = "doc.json"
RUN_FILE = "run.json"
FAILURES_FILE = "failures.jsonl"
SLUG_MAX = 40
HASH_CHARS = 12
OPTIONS_HASH_CHARS = 8

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slug_for(url: str) -> str:
    """The last part of the URL, lower-cased, without its extension, at most 40 characters."""
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    tail = re.sub(r"\.pdf(-\d+)?$", "", tail, flags=re.IGNORECASE)
    slug = _SLUG_STRIP.sub("-", tail.lower()).strip("-")[:SLUG_MAX].strip("-")
    return slug or "doc"


def source_sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def doc_id_for(url: str, pdf_bytes: bytes) -> str:
    """``<slug>_<first 12 hex of sha256(bytes)>``."""
    return f"{slug_for(url)}_{source_sha256(pdf_bytes)[:HASH_CHARS]}"


def options_hash(options: dict[str, Any]) -> str:
    """8 hex characters of the SHA-256 of the options as canonical JSON (sorted keys)."""
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:OPTIONS_HASH_CHARS]


def parse_folder(root: Path, doc_id: str, opts_hash: str) -> Path:
    """``<root>/<doc-id>/docling@<options hash>/``."""
    return Path(root) / doc_id / f"{PARSER_NAME}@{opts_hash}"


def parser_version(docling_version: str, opts_hash: str) -> str:
    """The ``parser_version`` of a Mongo row: ``<docling version>+<options hash>``."""
    return f"{docling_version}+{opts_hash}"
