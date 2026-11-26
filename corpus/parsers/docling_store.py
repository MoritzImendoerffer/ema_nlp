"""Where a Docling parse is stored, and under which names (backlog row 17).

Pure Python: no Docling import, so the retrieval environment (``.venv``) and the gate can
use and test it. The parse environment imports it too.

Per PDF one folder::

    <parsed root>/<doc-id>/docling@<options hash, 8 hex>/
        doc.raw.json   Docling's document as the parser returned it, without images
        doc.json       the same after post-processing (rebuilt from doc.raw.json at any time)
        run.json       the run record: source hash, versions, model revisions, options, counts

The document id is ``<slug>_<hash12>``: the last part of the URL, cut to 40 characters,
and the first 12 hex characters of the SHA-256 of the PDF bytes. With 6 hex characters,
about 66,000 PDFs would give an expected 4% chance of two different PDFs sharing a folder.
Two PDFs with the same bytes share one folder on purpose, and are parsed once.
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


# ── the writer (TASK-009) ────────────────────────────────────────────────────

# MongoDB refuses a document over 16 MB. The largest legacy row holds 12.45 million
# characters; the row's text is cut at this many UTF-8 bytes and the cut is recorded.
MONGO_TEXT_MAX_BYTES = 14 * 1024 * 1024
RUN_SCHEMA_VERSION = 1


def _dump(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_parse(folder: Path, raw_doc: dict[str, Any], doc: dict[str, Any], run: dict[str, Any]) -> Path:
    """Write the three files of one parse, all or nothing.

    The files go into a staging folder beside ``folder``. Only when all three are written
    does the staging folder replace ``folder``: the previous folder is renamed aside, the
    new one moved in, and the previous one deleted. A failure before the swap leaves the
    previous folder untouched and removes the staging folder.
    """
    import shutil

    folder = Path(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    stage = folder.with_name(folder.name + ".tmp")
    old = folder.with_name(folder.name + ".old")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    try:
        for name, obj in ((RAW_FILE, raw_doc), (DOC_FILE, doc), (RUN_FILE, run)):
            (stage / name).write_bytes(_dump(obj))
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    if old.exists():
        shutil.rmtree(old)
    if folder.exists():
        folder.rename(old)
    stage.rename(folder)
    if old.exists():
        shutil.rmtree(old)
    return folder


def append_failure(root: Path, *, url: str, doc_id: str, sha256: str, error: str) -> None:
    """One line per failed or partial document in ``<root>/failures.jsonl``; no folder is written."""
    from datetime import UTC, datetime

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    line = {"url": url, "doc_id": doc_id, "sha256": sha256, "error": error,
            "at": datetime.now(UTC).isoformat(timespec="seconds")}
    with open(root / FAILURES_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def run_record(*, url: str, doc_id: str, source_sha: str, options: dict[str, Any], opts_hash: str,
               versions: dict[str, str], counts: dict[str, int], seconds: float, device: str) -> dict[str, Any]:
    """The content of run.json."""
    from datetime import UTC, datetime

    return {"schema_version": RUN_SCHEMA_VERSION, "doc_id": doc_id, "url": url,
            "source_sha256": source_sha, "parser": PARSER_NAME, "options": options,
            "options_hash": opts_hash, "versions": versions, "counts": counts,
            "seconds": round(seconds, 2), "device": device,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds")}


def mongo_row(*, url: str, doc_id: str, folder_rel: str, source_sha: str, markdown: str,
              counts: dict[str, int], docling_version: str, opts_hash: str) -> Any:
    """The ``parsed_documents`` row of one parse, with the text cut below MongoDB's limit.

    Written only when the batch command is given ``--write-mongo``: under decision F a docling
    row for a URL without a legacy row would be selected by the next graph build.
    """
    from datetime import UTC, datetime

    from corpus.parsers.base import ParsedDocument

    data = markdown.encode("utf-8")
    truncated = len(data) > MONGO_TEXT_MAX_BYTES
    text = data[:MONGO_TEXT_MAX_BYTES].decode("utf-8", errors="ignore") if truncated else markdown
    meta = {"doc_id": doc_id, "folder": folder_rel, "source_sha256": source_sha, "counts": counts,
            "text_truncated": truncated}
    return ParsedDocument(url=url, parser=PARSER_NAME, parser_version=parser_version(docling_version, opts_hash),
                          parsed_at=datetime.now(UTC), content_type="application/pdf", text=text,
                          text_format="markdown", error="", meta=meta)
