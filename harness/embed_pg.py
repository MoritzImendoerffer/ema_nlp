"""BGE embedder + pgvector ingest pipeline.

This module hosts two layers:

* `Embedder` — thin wrapper around the LlamaIndex BGE-large-en-v1.5 embedding
  model with CUDA autodetection. Used by both the FAISS (legacy) and pgvector
  (new) paths; here we configure LlamaIndex Settings via
  `harness.providers.configure_embed_model` and call
  `Settings.embed_model.get_text_embedding_batch`.

* `sync(parser_preference, ...)` — parser-agnostic sync (MIGR-007). Reads
  already-parsed text from the Mongo ``parsed_documents`` collection,
  selects the preferred parser row per URL, hash-checks against
  ``documents.parsed_text_hash`` to skip unchanged content, and otherwise
  re-chunks/re-embeds/upserts. The legacy `--source pdfs|html` path
  remains as `ingest_source` until MIGR-008 wires the synthetic reader.

CLI:
    python -m harness.embed_pg [--batch-size 16] [--limit N] [--dry-run]
        Default: sync(parsed_documents) with the parser_preference defaults
        (overridden in MIGR-009 via --parser-preference).
    python -m harness.embed_pg --source pdfs|html [--force] [--limit N]
        Legacy ingest from parsed_pdfs/web_items via normalise_pdf_doc /
        normalise_html_doc.
    python -m harness.embed_pg --smoke
        Embedder shape smoke (8x1024).

`chunk_id = sha256(doc_id || chunk_index || normalised_text)` so re-running is
a no-op for identical inputs (ON CONFLICT DO NOTHING). The new sync's
hash-skip path keys on `parsed_text_hash` so unchanged docs never reach
the chunker/embedder at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from llama_index.core.settings import Settings
from tqdm import tqdm

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import MONGO_DB, MONGO_URI  # noqa: E402
from corpus.ingestion.chunker import ChunkConfig, chunk_markdown  # noqa: E402
from corpus.ingestion.link_extractor import (  # noqa: E402
    Link,
    extract_from_html,
    extract_from_markdown,
    extract_reference_numbers,
    extract_see_qa,
)
from corpus.ingestion.pdf_normaliser import DocumentInput, normalise_pdf_doc  # noqa: E402
from corpus.metadata.text_metadata import text_metadata  # noqa: E402
from corpus.metadata.url_metadata import url_metadata  # noqa: E402
from corpus.parsers.base import ParsedDocument  # noqa: E402
from harness.embed import EMBED_DIM, EMBED_MODEL_NAME  # noqa: E402 — re-export
from harness.pg import queries as Q  # noqa: E402
from harness.pg.conn import close_pool, get_pool  # noqa: E402
from harness.providers import configure_embed_model  # noqa: E402

DEFAULT_PARSER_PREFERENCE: dict[str, list[str]] = {
    "application/pdf": ["pymupdf4llm"],
    "text/html": ["trafilatura"],
}

# content_type → source_type (the schema CHECK constraint accepts pdf|html).
_CONTENT_TYPE_TO_SOURCE_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "text/html": "html",
}

_PREFERENCE_YAML = _REPO_ROOT / "harness" / "configs" / "parser_preference.yaml"


def load_parser_preference(
    path: Path | None = None,
    *,
    overrides: list[str] | None = None,
) -> dict[str, list[str]]:
    """Load parser_preference.yaml and apply CLI overrides.

    Each override is ``content_type=parser`` (e.g.
    ``'application/pdf=llamahub_pdf'``); per-content_type the override
    fully replaces the YAML default. Missing YAML file falls back to
    ``DEFAULT_PARSER_PREFERENCE``.
    """
    import yaml

    path = path or _PREFERENCE_YAML
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must contain a mapping at top level; got {type(raw).__name__}")
        preference: dict[str, list[str]] = {
            str(k): [str(v) for v in (vs or [])] for k, vs in raw.items()
        }
    else:
        _log.warning("parser_preference.yaml not found at %s; using built-in default", path)
        preference = {k: list(v) for k, v in DEFAULT_PARSER_PREFERENCE.items()}

    for override in overrides or []:
        if "=" not in override:
            raise ValueError(
                f"--parser-preference override must be 'content_type=parser_name'; got {override!r}"
            )
        ct, parser = override.split("=", 1)
        ct, parser = ct.strip(), parser.strip()
        if not ct or not parser:
            raise ValueError(f"invalid --parser-preference override: {override!r}")
        preference[ct] = [parser]
    return preference

_log = logging.getLogger(__name__)

Source = Literal["pdfs", "html"]


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


def _detect_device() -> str:
    try:
        import torch  # heavy import; only used to pick device
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


class Embedder:
    """LlamaIndex-backed BGE embedder. Lazy: model loads on first use."""

    def __init__(
        self,
        *,
        device: str | None = None,
        batch_size: int = 32,
        model_name: str | None = None,
    ) -> None:
        self.device = device or _detect_device()
        self.batch_size = batch_size
        self.model_name = model_name or EMBED_MODEL_NAME
        self._configured = False

    def _ensure(self) -> None:
        if self._configured:
            return
        configure_embed_model(
            model_name=self.model_name, device=self.device, embed_batch_size=self.batch_size
        )
        _log.info(
            "Embedder ready: model=%s device=%s batch_size=%d dim=%d",
            self.model_name, self.device, self.batch_size, EMBED_DIM,
        )
        self._configured = True

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure()
        vectors = Settings.embed_model.get_text_embedding_batch(list(texts))
        return [list(map(float, v)) for v in vectors]


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------


def compute_doc_id(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def compute_chunk_id(doc_id: str, chunk_index: int, text: str) -> str:
    h = hashlib.sha256()
    h.update(doc_id.encode("utf-8"))
    h.update(str(chunk_index).encode("utf-8"))
    h.update(text.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Mongo streaming
# ---------------------------------------------------------------------------


def _iter_pdf_docs(limit: int | None) -> Iterator[dict[str, Any]]:
    from pymongo import MongoClient

    client = MongoClient(MONGO_URI)
    col = client[MONGO_DB]["parsed_pdfs"]
    # Sort by _id (URL) for deterministic --limit slices across runs (NARR-008).
    cursor = col.find({"error": ""}, no_cursor_timeout=False).sort("_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)
    try:
        yield from cursor
    finally:
        cursor.close()
        client.close()


def _iter_html_docs(limit: int | None) -> Iterator[dict[str, Any]]:
    """HTML source iterator. Defined here so source='html' dispatches cleanly;
    the normaliser arrives in NARR-009 and the wiring lands in NARR-010."""
    from pymongo import MongoClient

    client = MongoClient(MONGO_URI)
    col = client[MONGO_DB]["web_items"]
    cursor = col.find({"content_type": "text/html"}, no_cursor_timeout=False).sort("_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)
    try:
        yield from cursor
    finally:
        cursor.close()
        client.close()


# ---------------------------------------------------------------------------
# Per-doc processing
# ---------------------------------------------------------------------------


@dataclass
class _PreparedDoc:
    doc_id: str
    document: DocumentInput
    chunks: list[dict[str, Any]]  # rows ready to be inserted (sans embedding)
    links: list[dict[str, Any]]   # link rows ready for INSERT_LINK


def _link_row(doc_id: str, chunk_id: str | None, link: Link) -> dict[str, Any]:
    return {
        "src_doc_id": doc_id,
        "tgt_url": link.tgt_url,
        "tgt_doc_id": None,
        "link_type": link.link_type,
        "anchor": link.anchor,
        "chunk_id": chunk_id,
    }


def _collect_text_links(
    doc_id: str, chunk_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per-chunk extraction (hyperlink + reference_number + see_qa).

    De-duplicated by (tgt_url, link_type) within the document so the first
    chunk that mentions a target wins the chunk_id attribution. ON CONFLICT
    in the DB layer handles any cross-batch duplicates."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for c in chunk_rows:
        chunk_id = c["chunk_id"]
        text = c["text"]
        for link in (
            *extract_from_markdown(text),
            *extract_reference_numbers(text),
            *extract_see_qa(text),
        ):
            key = (link.tgt_url, link.link_type)
            if key in seen:
                continue
            seen.add(key)
            out.append(_link_row(doc_id, chunk_id, link))
    return out


def _collect_html_links(doc_id: str, html: str, base_url: str) -> list[dict[str, Any]]:
    """Anchor-tag extraction on the raw HTML; chunk_id stays None."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for link in extract_from_html(html, base_url):
        key = (link.tgt_url, link.link_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(_link_row(doc_id, None, link))
    return out


def _build_chunk_rows(
    doc_id: str, raw_chunks: list[Any]
) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": compute_chunk_id(doc_id, c.chunk_index, c.text),
            "doc_id": doc_id,
            "chunk_index": c.chunk_index,
            "text": c.text,
            "heading_path": c.heading_path,
            "token_count": c.token_count,
        }
        for c in raw_chunks
    ]


def _prepare_pdf(mongo_doc: dict, chunk_config: ChunkConfig) -> _PreparedDoc | None:
    norm = normalise_pdf_doc(mongo_doc)
    if norm is None:
        return None
    doc_id = compute_doc_id(norm.source_url)
    raw_chunks = chunk_markdown(norm.markdown, chunk_config)
    if not raw_chunks:
        return None
    rows = _build_chunk_rows(doc_id, raw_chunks)
    links = _collect_text_links(doc_id, rows)
    return _PreparedDoc(doc_id=doc_id, document=norm, chunks=rows, links=links)


def _prepare_html(mongo_doc: dict, chunk_config: ChunkConfig) -> _PreparedDoc | None:
    # Defer import so NARR-007 doesn't hard-require NARR-009 to land first.
    from corpus.ingestion.html_normaliser import normalise_html_doc  # noqa: WPS433

    norm = normalise_html_doc(mongo_doc)
    if norm is None:
        return None
    doc_id = compute_doc_id(norm.source_url)
    raw_chunks = chunk_markdown(norm.markdown, chunk_config)
    if not raw_chunks:
        return None
    rows = _build_chunk_rows(doc_id, raw_chunks)
    links = _collect_text_links(doc_id, rows)
    # html_raw is a 1-element list in web_items; unwrap defensively
    html_raw = mongo_doc.get("html_raw")
    if isinstance(html_raw, list):
        html_raw = html_raw[0] if html_raw else None
    if isinstance(html_raw, str):
        existing = {(row["tgt_url"], row["link_type"]) for row in links}
        for row in _collect_html_links(doc_id, html_raw, norm.source_url):
            key = (row["tgt_url"], row["link_type"])
            if key in existing:
                continue
            existing.add(key)
            links.append(row)
    return _PreparedDoc(doc_id=doc_id, document=norm, chunks=rows, links=links)


_PREPARERS = {
    "pdfs": _prepare_pdf,
    "html": _prepare_html,
}

_SOURCE_TO_COLLECTION = {
    "pdfs": ("parsed_pdfs", _iter_pdf_docs),
    "html": ("web_items", _iter_html_docs),
}


def _source_url_of(mongo_doc: dict, source: Source) -> str | None:
    """Best-effort URL extraction for log lines on skipped docs.

    PDFs store the URL as ``_id``; HTML docs store it as ``url`` (a 1-element
    list per the scrapy pipeline). Mirrors the unwrap logic in
    ``normalise_html_doc`` / ``normalise_pdf_doc``.
    """
    if source == "pdfs":
        val = mongo_doc.get("_id") or mongo_doc.get("source_url")
        return val if isinstance(val, str) else None
    if source == "html":
        val = mongo_doc.get("url") or mongo_doc.get("_id")
        if isinstance(val, list):
            val = val[0] if val else None
        return val if isinstance(val, str) else None
    return None


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def _upsert_batch(
    pool,
    prepared: list[_PreparedDoc],
    vectors: list[list[float]],
    parser_fields: list[dict[str, Any]] | None = None,
) -> tuple[int, int, int]:
    """Insert documents + chunks + links for a batch.

    ``parser_fields`` is an aligned list of dicts containing the new
    MIGR-006 columns (parser, parser_version, parsed_at, parsed_text,
    parsed_text_hash). Callers that don't know parser identity (legacy
    ingest_source) pass None — the columns are filled with NULL.

    Returns (n_docs, n_chunks_attempted, n_links_attempted).
    """
    if not prepared:
        return 0, 0, 0
    doc_rows = []
    for i, p in enumerate(prepared):
        d = p.document
        pf = parser_fields[i] if parser_fields else {}
        doc_rows.append(
            {
                "doc_id": p.doc_id,
                "source_url": d.source_url,
                "source_type": d.source_type,
                "title": d.title,
                "topic_path": d.topic_path,
                "reference_number": d.reference_number,
                "committee": d.committee,
                "revision": d.revision,
                "last_updated": d.last_updated,
                "raw_byte_size": d.raw_byte_size,
                "parser": pf.get("parser"),
                "parser_version": pf.get("parser_version"),
                "parsed_at": pf.get("parsed_at"),
                "parsed_text": pf.get("parsed_text"),
                "parsed_text_hash": pf.get("parsed_text_hash"),
                "meta": json.dumps(d.meta or {}),
            }
        )
    chunk_rows = []
    idx = 0
    for p in prepared:
        for row in p.chunks:
            chunk_rows.append({**row, "embedding": vectors[idx]})
            idx += 1
    assert idx == len(vectors), f"vector/chunk count mismatch: {idx} != {len(vectors)}"

    link_rows = [row for p in prepared for row in p.links]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(Q.UPSERT_DOCUMENT, doc_rows)
            cur.executemany(Q.INSERT_CHUNK, chunk_rows)
            if link_rows:
                cur.executemany(Q.INSERT_LINK, link_rows)
        conn.commit()
    return len(doc_rows), len(chunk_rows), len(link_rows)


def _delete_for_urls(pool, source_urls: list[str]) -> int:
    """Delete chunks (+ link rows) for the given source URLs. Returns affected docs."""
    if not source_urls:
        return 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(Q.DOC_IDS_BY_SOURCE_URLS, {"source_urls": source_urls})
            doc_ids = [r[0] for r in cur.fetchall()]
            if not doc_ids:
                return 0
            cur.execute(Q.DELETE_LINKS_BY_DOC, {"doc_ids": doc_ids})
            cur.execute(Q.DELETE_CHUNKS_BY_DOC, {"doc_ids": doc_ids})
        conn.commit()
    return len(doc_ids)


# ---------------------------------------------------------------------------
# New parser-agnostic sync (MIGR-007)
# ---------------------------------------------------------------------------


@dataclass
class SyncStats:
    seen: int = 0
    selected: int = 0
    new: int = 0
    re_synced: int = 0
    skipped_unchanged: int = 0
    skipped_no_preferred_parser: int = 0
    chunks_written: int = 0
    links_written: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "seen": self.seen,
            "selected": self.selected,
            "new": self.new,
            "re_synced": self.re_synced,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_no_preferred_parser": self.skipped_no_preferred_parser,
            "chunks_written": self.chunks_written,
            "links_written": self.links_written,
            "errors": self.errors,
        }


def compute_parsed_text_hash(text: str) -> str:
    """sha256 over the parsed text with trailing whitespace trimmed.

    Drives the sync hash-skip path: when the hash matches the value already
    in ``documents.parsed_text_hash`` the row is a no-op (no re-chunk, no
    re-embed). The trim guards against trivial whitespace drift between
    parser runs.
    """
    normalised = text.rstrip() if isinstance(text, str) else ""
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _mongo_row_to_parsed_doc(row: dict[str, Any]) -> ParsedDocument:
    """Convert a `parsed_documents` Mongo row back to a ParsedDocument.

    Mongo strips tzinfo on storage; we restore it to UTC so the
    ParsedDocument validator (which requires a datetime) sees a
    well-formed value.
    """
    from datetime import UTC

    parsed_at_raw = row.get("parsed_at")
    if not isinstance(parsed_at_raw, datetime):
        raise ValueError(
            f"parsed_documents row for {row.get('url')!r} is missing a datetime "
            f"parsed_at field; got {type(parsed_at_raw).__name__}"
        )
    parsed_at = (
        parsed_at_raw.replace(tzinfo=UTC) if parsed_at_raw.tzinfo is None else parsed_at_raw
    )
    return ParsedDocument(
        url=row["url"],
        parser=row["parser"],
        parser_version=row["parser_version"],
        parsed_at=parsed_at,
        content_type=row["content_type"],
        text=row.get("text", "") or "",
        text_format=row.get("text_format", "markdown"),
        error=row.get("error", "") or "",
        meta=dict(row.get("meta") or {}),
    )


def _select_preferred(
    rows: list[dict[str, Any]],
    preference: dict[str, list[str]],
) -> dict[str, Any] | None:
    """Pick the single preferred parser row from rows for the same URL.

    Iterates ``preference[content_type]`` and returns the first matching
    row whose ``error`` is empty. Returns ``None`` when no row qualifies.
    """
    if not rows:
        return None
    # Group by content_type (typically one per URL, but be defensive).
    by_ct: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_ct.setdefault(r["content_type"], []).append(r)
    for ct in sorted(by_ct.keys()):
        pref = preference.get(ct, [])
        ct_rows = by_ct[ct]
        for parser_name in pref:
            for r in ct_rows:
                if r["parser"] == parser_name and not r.get("error"):
                    return r
    return None


def _iter_preferred_parsed_documents(
    *,
    client,
    preference: dict[str, list[str]],
    url_filter: list[str] | None = None,
    parser_filter: list[str] | None = None,
    since: datetime | None = None,
    stats: SyncStats | None = None,
) -> Iterator[ParsedDocument]:
    """Stream the preferred ParsedDocument per URL from `parsed_documents`."""
    col = client[MONGO_DB]["parsed_documents"]
    query: dict[str, Any] = {}
    if url_filter:
        query["url"] = {"$in": list(url_filter)}
    if since is not None:
        query["parsed_at"] = {"$gte": since}
    if parser_filter:
        query["parser"] = {"$in": list(parser_filter)}

    # distinct() returns a list of unique URLs matching the filter.
    urls = col.distinct("url", query)
    for url in urls:
        row_query: dict[str, Any] = {"url": url}
        if parser_filter:
            row_query["parser"] = {"$in": list(parser_filter)}
        rows = list(col.find(row_query))
        if stats is not None:
            stats.seen += 1
        selected = _select_preferred(rows, preference)
        if selected is None:
            _log.warning(
                "no preferred parser row for %s (had %d candidates)", url, len(rows)
            )
            if stats is not None:
                stats.skipped_no_preferred_parser += 1
            continue
        if stats is not None:
            stats.selected += 1
        yield _mongo_row_to_parsed_doc(selected)


def _document_input_from_parsed(parsed: ParsedDocument) -> DocumentInput:
    """Project a ParsedDocument into the existing DocumentInput shape that
    `_PreparedDoc` and `_upsert_batch` consume. Lets us reuse the chunker
    + link extractor + upsert path without further refactoring."""
    um = url_metadata(parsed.url)
    tm = text_metadata(parsed.text, parsed.text_format)
    source_type = _CONTENT_TYPE_TO_SOURCE_TYPE.get(parsed.content_type)
    if source_type is None:
        # Fall back to the URL-shape hint when content_type is unfamiliar.
        source_type = um.source_type if um.source_type in {"pdf", "html"} else "html"
    return DocumentInput(
        source_url=parsed.url,
        source_type=source_type,  # type: ignore[arg-type]
        title=tm.title,
        topic_path=um.topic_path,
        reference_number=tm.reference_number,
        committee=tm.committee,
        revision=tm.revision,
        last_updated=tm.last_updated,
        raw_byte_size=len(parsed.text.encode("utf-8")),
        markdown=parsed.text,
        meta={
            **(parsed.meta or {}),
            "parser": parsed.parser,
            "parser_version": parsed.parser_version,
        },
    )


def _prepare_from_parsed_doc(
    parsed: ParsedDocument, chunk_config: ChunkConfig
) -> _PreparedDoc | None:
    if not parsed.text or parsed.error:
        return None
    doc_input = _document_input_from_parsed(parsed)
    doc_id = compute_doc_id(parsed.url)
    raw_chunks = chunk_markdown(parsed.text, chunk_config)
    if not raw_chunks:
        return None
    rows = _build_chunk_rows(doc_id, raw_chunks)
    links = _collect_text_links(doc_id, rows)
    return _PreparedDoc(doc_id=doc_id, document=doc_input, chunks=rows, links=links)


def _fetch_existing_hashes(pool, doc_ids: list[str]) -> dict[str, str | None]:
    """Return doc_id → parsed_text_hash for the given doc_ids. Missing rows
    map to None (i.e. never-seen-before)."""
    if not doc_ids:
        return {}
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(Q.PARSED_HASH_BY_DOC_IDS, {"doc_ids": doc_ids})
            rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def sync(
    parser_preference: dict[str, list[str]] | None = None,
    *,
    source: Literal["parsed_documents", "legacy"] = "parsed_documents",
    parsed_documents_stream: Iterable[ParsedDocument] | None = None,
    since: datetime | None = None,
    parser_filter: list[str] | None = None,
    url_filter: list[str] | None = None,
    batch_size: int = 16,
    dry_run: bool = False,
    chunk_config: ChunkConfig | None = None,
    embedder: Embedder | None = None,
    client=None,
) -> SyncStats:
    """Parser-agnostic sync from `parsed_documents` into pgvector.

    For each preferred (url, parser, parser_version) selected by
    ``parser_preference``, the sync:

      1. Reads ``parsed_text`` from the Mongo row.
      2. Computes ``sha256`` of the trimmed text.
      3. If the hash matches ``documents.parsed_text_hash`` for the same
         doc_id, increments ``skipped_unchanged`` and moves on — zero
         chunker/embedder work.
      4. Otherwise: deletes the doc's existing chunks + links, re-chunks,
         re-embeds, and upserts ``documents`` + ``chunks`` + ``links``.

    ``parsed_documents_stream`` lets callers supply a pre-built iterator
    (used by the synthetic-legacy-reader path in MIGR-008 and by tests).
    When None, the function reads from the Mongo ``parsed_documents``
    collection and applies the preference selector itself.
    """
    parser_preference = parser_preference or DEFAULT_PARSER_PREFERENCE
    chunk_config = chunk_config or ChunkConfig()
    embedder = embedder or Embedder(batch_size=32)
    pool = get_pool()
    stats = SyncStats()

    own_client = False
    if parsed_documents_stream is None:
        if client is None:
            from pymongo import MongoClient

            client = MongoClient(MONGO_URI)
            own_client = True
        if source == "legacy":
            from corpus.sources.synthetic_legacy_reader import (
                iter_parsed_documents_from_legacy,
            )

            legacy_iter = iter_parsed_documents_from_legacy(client=client)
            # Apply url_filter at the iterator level so the legacy reader
            # can scan once and the sync sees only matching docs.
            if url_filter:
                allowed = set(url_filter)
                legacy_iter = (d for d in legacy_iter if d.url in allowed)
            parsed_documents_stream = legacy_iter
        else:
            parsed_documents_stream = _iter_preferred_parsed_documents(
                client=client,
                preference=parser_preference,
                url_filter=url_filter,
                parser_filter=parser_filter,
                since=since,
                stats=stats,
            )

    pending: list[tuple[ParsedDocument, _PreparedDoc, str]] = []  # (parsed, prep, hash)

    def _flush() -> None:
        if not pending:
            return
        doc_ids = [prep.doc_id for _, prep, _ in pending]
        existing = _fetch_existing_hashes(pool, doc_ids)
        to_write: list[tuple[ParsedDocument, _PreparedDoc, str]] = []
        for parsed, prep, h in pending:
            prior_hash = existing.get(prep.doc_id)
            if prior_hash == h:
                stats.skipped_unchanged += 1
                continue
            if prior_hash is None:
                stats.new += 1
            else:
                stats.re_synced += 1
            to_write.append((parsed, prep, h))

        if not to_write:
            pending.clear()
            return

        texts = [row["text"] for _, prep, _ in to_write for row in prep.chunks]
        link_count = sum(len(prep.links) for _, prep, _ in to_write)

        if dry_run:
            stats.chunks_written += len(texts)
            stats.links_written += link_count
            pending.clear()
            return

        _delete_for_urls(pool, [parsed.url for parsed, _, _ in to_write])
        vectors = embedder.encode(texts)
        prepared_list = [prep for _, prep, _ in to_write]
        parser_fields = [
            {
                "parser": parsed.parser,
                "parser_version": parsed.parser_version,
                "parsed_at": parsed.parsed_at,
                "parsed_text": parsed.text,
                "parsed_text_hash": h,
            }
            for parsed, _, h in to_write
        ]
        _, n_chunks, n_links = _upsert_batch(
            pool, prepared_list, vectors, parser_fields=parser_fields
        )
        stats.chunks_written += n_chunks
        stats.links_written += n_links
        pending.clear()

    try:
        for parsed in parsed_documents_stream:
            try:
                prep = _prepare_from_parsed_doc(parsed, chunk_config)
            except Exception as exc:  # noqa: BLE001
                _log.warning("prepare failed for %s: %s", parsed.url, exc)
                stats.errors += 1
                continue
            if prep is None:
                continue
            h = compute_parsed_text_hash(parsed.text)
            pending.append((parsed, prep, h))
            if len(pending) >= batch_size:
                _flush()
        _flush()
    finally:
        if own_client and client is not None:
            client.close()

    _log.info(
        "sync done: %s",
        " ".join(f"{k}={v}" for k, v in stats.as_dict().items()),
    )
    return stats


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_source(
    source: Source,
    *,
    batch_size: int = 16,
    limit: int | None = None,
    force: bool = False,
    chunk_config: ChunkConfig | None = None,
    embedder: Embedder | None = None,
) -> dict[str, int]:
    """Stream `source` from Mongo and upsert into PG. Returns counts.

    `batch_size` is the number of documents accumulated before each flush
    (embedding + executemany). The embedder's internal sentence-batch is
    independent (HuggingFaceEmbedding embed_batch_size, default 32 here).
    """
    if source not in _PREPARERS:
        raise ValueError(f"Unsupported source: {source!r}")

    chunk_config = chunk_config or ChunkConfig()
    embedder = embedder or Embedder(batch_size=32)
    preparer = _PREPARERS[source]
    _, iter_fn = _SOURCE_TO_COLLECTION[source]
    pool = get_pool()

    totals = {
        "docs_seen": 0,
        "docs_kept": 0,
        "docs_skipped": 0,
        "chunks_written": 0,
        "links_written": 0,
        "errors": 0,
    }
    pending: list[_PreparedDoc] = []
    pending_urls: list[str] = []

    def _flush() -> None:
        if not pending:
            return
        if force:
            _delete_for_urls(pool, [p.document.source_url for p in pending])
        texts = [row["text"] for p in pending for row in p.chunks]
        vectors = embedder.encode(texts)
        n_docs, n_chunks, n_links = _upsert_batch(pool, pending, vectors)
        totals["docs_kept"] += n_docs
        totals["chunks_written"] += n_chunks
        totals["links_written"] += n_links
        pending.clear()
        pending_urls.clear()

    iterator = iter_fn(limit)
    progress = tqdm(iterator, desc=f"ingest {source}", unit="doc", total=limit)
    try:
        for mongo_doc in progress:
            totals["docs_seen"] += 1
            try:
                prepared = preparer(mongo_doc, chunk_config)
            except Exception as e:  # noqa: BLE001
                _log.warning("normalise/chunk failed for %r: %s", mongo_doc.get("_id"), e)
                totals["errors"] += 1
                continue
            if prepared is None:
                totals["docs_skipped"] += 1
                _log.info(
                    "skipped %s: %s (landing page, empty extraction, or no chunks)",
                    source, _source_url_of(mongo_doc, source) or "<no-url>",
                )
                continue
            pending.append(prepared)
            pending_urls.append(prepared.document.source_url)
            if len(pending) >= batch_size:
                _flush()
        _flush()
    finally:
        progress.close()

    _log.info(
        "ingest %s done: seen=%d kept=%d skipped=%d chunks=%d links=%d errors=%d",
        source, totals["docs_seen"], totals["docs_kept"],
        totals["docs_skipped"], totals["chunks_written"],
        totals["links_written"], totals["errors"],
    )
    return totals


# ---------------------------------------------------------------------------
# Smoke + CLI
# ---------------------------------------------------------------------------


def _smoke_test() -> int:
    """Verify Embedder builds, runs, and returns (8, 1024) shapes."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    embedder = Embedder()
    texts = [
        "Acceptable intake (AI) is a toxicology limit in ng/day.",
        "EMA/CHMP/13279/2017 references a specific committee work plan.",
        "Reference Listed Drugs are used in bioequivalence studies.",
        "ICH M7 sets the mutagenic-impurity control framework.",
        "Class 1 solvents are residual solvents to avoid.",
        "Q3D guideline addresses metallic-impurity exposure.",
        "Variation type II requires new data submission.",
        "PRAC reviews pharmacovigilance signals quarterly.",
    ]
    vectors = embedder.encode(texts)
    assert len(vectors) == 8 and all(len(v) == EMBED_DIM for v in vectors)
    print(f"embed_pg.Embedder smoke OK: 8x{EMBED_DIM} vectors, device={embedder.device}")
    return 0


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Embed + upsert EMA sources into pgvector.")
    p.add_argument(
        "--source",
        choices=list(_PREPARERS),
        help="Legacy ingest source (pdfs|html). Default mode runs sync() against parsed_documents.",
    )
    p.add_argument("--batch-size", type=int, default=16, help="docs per flush")
    p.add_argument("--limit", type=int, default=None, help="max docs (legacy --source mode)")
    p.add_argument(
        "--force",
        action="store_true",
        help="legacy --source mode: delete chunks/links for affected URLs before re-inserting",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="sync mode: compute hash-skip + chunk counts without writing",
    )
    p.add_argument(
        "--url-filter",
        action="append",
        default=None,
        help="sync mode: only process this URL (repeatable)",
    )
    p.add_argument(
        "--parser-filter",
        action="append",
        default=None,
        help="sync mode: restrict to these parser names (repeatable)",
    )
    p.add_argument(
        "--parser-preference",
        action="append",
        default=None,
        help=(
            "Override the YAML default per content_type, e.g. "
            "'--parser-preference application/pdf=llamahub_pdf' (repeatable)."
        ),
    )
    p.add_argument(
        "--legacy-source",
        action="store_true",
        help="sync mode: read from legacy parsed_pdfs+web_items via the synthetic reader",
    )
    p.add_argument("--smoke", action="store_true", help="run Embedder smoke and exit")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.smoke:
        return _smoke_test()
    try:
        if args.source:
            totals = ingest_source(
                args.source,
                batch_size=args.batch_size,
                limit=args.limit,
                force=args.force,
            )
            print(json.dumps(totals, indent=2))
        else:
            preference = load_parser_preference(overrides=args.parser_preference)
            stats = sync(
                parser_preference=preference,
                source="legacy" if args.legacy_source else "parsed_documents",
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                url_filter=args.url_filter,
                parser_filter=args.parser_filter,
            )
            print(json.dumps(stats.as_dict(), indent=2))
    finally:
        close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
