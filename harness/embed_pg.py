"""BGE embedder + pgvector ingest pipeline.

This module hosts two layers:

* `Embedder` — thin wrapper around the LlamaIndex BGE-large-en-v1.5 embedding
  model with CUDA autodetection. Used by both the FAISS (legacy) and pgvector
  (new) paths; here we configure LlamaIndex Settings via
  `harness.providers.configure_embed_model` and call
  `Settings.embed_model.get_text_embedding_batch`.

* `ingest_source` — CLI-driven loop that streams MongoDB docs, normalises,
  chunks, embeds in batches, and bulk-upserts into the `documents` +
  `chunks` (+ `links`) tables. Sources: 'pdfs' (parsed_pdfs collection) and
  'html' (web_items collection).

CLI:
    python -m harness.embed_pg --source pdfs [--batch-size 16] [--limit 100] [--force]
    python -m harness.embed_pg --source html [--batch-size 16] [--limit 100] [--force]
    python -m harness.embed_pg --smoke

`chunk_id = sha256(doc_id || chunk_index || normalised_text)` so re-running is
a no-op for identical inputs (ON CONFLICT DO NOTHING). `--force` deletes the
chunks for the affected source URLs before re-inserting; the dependent links
rows are dropped as well to keep referential integrity clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass
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
from harness.embed import EMBED_DIM, EMBED_MODEL_NAME  # noqa: E402 — re-export
from harness.pg import queries as Q  # noqa: E402
from harness.pg.conn import close_pool, get_pool  # noqa: E402
from harness.providers import configure_embed_model  # noqa: E402

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
    pool, prepared: list[_PreparedDoc], vectors: list[list[float]]
) -> tuple[int, int, int]:
    """Insert documents + chunks + links for a batch.

    Returns (n_docs, n_chunks_attempted, n_links_attempted)."""
    if not prepared:
        return 0, 0, 0
    doc_rows = []
    for p in prepared:
        d = p.document
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
    p.add_argument("--source", choices=list(_PREPARERS), help="pdfs | html")
    p.add_argument("--batch-size", type=int, default=16, help="docs per flush")
    p.add_argument("--limit", type=int, default=None, help="max docs (None = all)")
    p.add_argument(
        "--force",
        action="store_true",
        help="delete chunks/links for affected URLs before re-inserting",
    )
    p.add_argument("--smoke", action="store_true", help="run Embedder smoke and exit")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.smoke:
        return _smoke_test()
    if not args.source:
        p.error("--source is required (or pass --smoke)")
    try:
        totals = ingest_source(
            args.source,
            batch_size=args.batch_size,
            limit=args.limit,
            force=args.force,
        )
        print(json.dumps(totals, indent=2))
    finally:
        close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
