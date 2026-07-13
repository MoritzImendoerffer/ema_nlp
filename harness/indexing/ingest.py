"""Ingestion — Mongo ``parsed_documents`` -> an in-memory LlamaIndex node graph.

Each source document becomes an :class:`IngestedDoc`:
  - an entity (page / PDF) identified by ``doc_id = sha256(url)`` + metadata
  - hierarchical chunk nodes (from ``chunking.chunk_document`` — parent/child kept)
  - ``links_to`` edges (from ``links.extract_links`` over the page's raw HTML)

Authoritative labels (``doc_type`` / ``audience`` / ``site_topic``) are joined
per URL from the Mongo ``document_metadata`` collection
(``harness.indexing.document_metadata``, populated by
``scripts/enrich_document_metadata.py``). When a page has no row there —
enrichment not run, or a brand-new URL — badges fall back to live extraction
from the page's raw HTML (``doc_type`` has no live fallback; it comes from the
EMA JSON export only).

This layer is pure data → IR; it needs no Neo4j and is unit-testable with
mongomock. ``harness.indexing.property_graph`` (LIR-007) maps the IR into a
Neo4j ``PropertyGraphIndex``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from llama_index.core.schema import BaseNode
from pymongo import MongoClient

from config import MONGO_DB, MONGO_URI
from corpus.metadata.text_metadata import text_metadata
from corpus.metadata.url_metadata import url_metadata
from harness.indexing.badges import extract_badges
from harness.indexing.chunking import chunk_document, doc_id_for
from harness.indexing.document_metadata import MetadataLookup, mongo_metadata_lookup
from harness.indexing.links import ExtractedLink, extract_links
from harness.indexing.profiles import ChunkingConfig, IndexProfile, ScopeConfig

_log = logging.getLogger(__name__)

PARSED_COLLECTION = "parsed_documents"
WEB_ITEMS_COLLECTION = "web_items"

HtmlLookup = Callable[[str], str | None]


@dataclass
class IngestedDoc:
    doc_id: str
    source_url: str
    source_type: str  # "pdf" | "html" | "unknown"
    title: str
    metadata: dict[str, Any]
    chunk_nodes: list[BaseNode] = field(default_factory=list)
    links: list[ExtractedLink] = field(default_factory=list)


def _source_type(content_type: str, url_guess: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "pdf"
    if "html" in ct:
        return "html"
    return url_guess


def _title_fallback(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    for ext in (".pdf", ".html", ".htm"):
        if tail.lower().endswith(ext):
            tail = tail[: -len(ext)]
    return tail.replace("_", " ").replace("-", " ").strip() or url


def _matches_topic(topic_path: str | None, prefix: str) -> bool:
    return bool(topic_path) and topic_path.startswith(prefix)


def mongo_html_lookup(client: MongoClient[Any]) -> HtmlLookup:
    """Best-effort raw-HTML fetch from ``web_items.html_raw`` (a 1-element list)."""
    col = client[MONGO_DB][WEB_ITEMS_COLLECTION]

    def _lookup(url: str) -> str | None:
        row = col.find_one({"url": url}, {"html_raw": 1})
        raw = (row or {}).get("html_raw")
        if isinstance(raw, list) and raw:
            return str(raw[0])
        return str(raw) if isinstance(raw, str) and raw else None

    return _lookup


def build_ingested_doc(
    pd: dict[str, Any],
    *,
    chunking: ChunkingConfig,
    html_lookup: HtmlLookup,
    metadata_lookup: MetadataLookup | None = None,
) -> IngestedDoc:
    url = pd["url"]
    text = pd.get("text", "") or ""
    um = url_metadata(url)
    tm = text_metadata(text, pd.get("text_format", "markdown"))
    source_type = _source_type(pd.get("content_type", ""), um.source_type)
    title = tm.title or _title_fallback(url)

    metadata: dict[str, Any] = {
        "source_type": source_type,
        "committee": tm.committee,
        "topic_path": um.topic_path,
        "reference_number": tm.reference_number,
        "revision": tm.revision,
        "last_updated": tm.last_updated.isoformat() if tm.last_updated else None,
        "parser": pd.get("parser"),
    }
    # Authoritative labels come from the enrichment collection when present;
    # its values (including nulls) win over live derivation so the stored row
    # is the single source of truth.
    meta_row = metadata_lookup(url) if metadata_lookup else None
    if meta_row is not None:
        metadata["doc_type"] = meta_row.get("doc_type")
        metadata["audience"] = meta_row.get("audience")
        metadata["site_topic"] = meta_row.get("site_topic")
    base_meta = {
        "source_type": source_type,
        "committee": tm.committee,
        "topic_path": um.topic_path,
        "reference_number": tm.reference_number,
    }
    chunk_nodes = chunk_document(
        text, source_url=url, title=title, base_metadata=base_meta, config=chunking
    )

    links: list[ExtractedLink] = []
    if source_type == "html":
        html = html_lookup(url)
        if html:
            links = extract_links(html, url)
            if meta_row is None:  # not enriched: derive badges live
                badges = extract_badges(html)
                metadata["audience"] = badges.audience
                metadata["site_topic"] = badges.site_topic

    return IngestedDoc(
        doc_id=doc_id_for(url),
        source_url=url,
        source_type=source_type,
        title=title,
        metadata=metadata,
        chunk_nodes=chunk_nodes,
        links=links,
    )


def iter_source_rows(
    scope: ScopeConfig,
    *,
    client: MongoClient[Any],
) -> Iterator[dict[str, Any]]:
    """Yield one clean ``parsed_documents`` row per URL, honouring the scope.

    URL-level filters (topic_prefix, limit) are applied here; the committee
    filter needs parsed text, so it is applied in :func:`ingest` after metadata
    derivation. One row per URL (first by URL sort) — the backfill writes a
    single parser per URL, so parser-preference selection is a later refinement.
    """
    col = client[MONGO_DB][PARSED_COLLECTION]
    seen: set[str] = set()
    yielded = 0
    # no_cursor_timeout: this cursor is iterated across a multi-hour embed pass and
    # a slower link-extraction pass; the server's default 10-min idle timeout can
    # expire it mid-iteration (CursorNotFound, code 43). Close it explicitly in the
    # finally so the server-side cursor is not leaked.
    cursor = col.find({"error": ""}, no_cursor_timeout=True).sort("url", 1)
    try:
        for row in cursor:
            url = row.get("url")
            if not url or url in seen:
                continue
            ct = (row.get("content_type") or "").lower()
            if "pdf" not in ct and "html" not in ct:
                continue
            if scope.topic_prefix and not _matches_topic(url_metadata(url).topic_path, scope.topic_prefix):
                continue
            seen.add(url)
            yield row
            yielded += 1
            # Over-fetch slightly when a committee filter will prune later.
            if scope.limit and not scope.committee and yielded >= scope.limit:
                return
    finally:
        cursor.close()


def ingest(
    profile: IndexProfile,
    *,
    mongo_client: MongoClient[Any] | None = None,
    html_lookup: HtmlLookup | None = None,
    metadata_lookup: MetadataLookup | None = None,
) -> list[IngestedDoc]:
    """Build the IR (list of IngestedDoc) for ``profile`` from Mongo."""
    scope = profile.index.scope
    chunking = profile.index.chunking
    owned = mongo_client is None
    client: MongoClient[Any] = MongoClient(MONGO_URI) if owned else mongo_client  # type: ignore[assignment]
    try:
        lookup = html_lookup or mongo_html_lookup(client)
        meta_lookup = metadata_lookup or mongo_metadata_lookup(client)
        meta_misses = 0

        def counted_meta_lookup(url: str) -> dict[str, Any] | None:
            nonlocal meta_misses
            row = meta_lookup(url)
            if row is None:
                meta_misses += 1
            return row

        out: list[IngestedDoc] = []
        for row in iter_source_rows(scope, client=client):
            doc = build_ingested_doc(
                row, chunking=chunking, html_lookup=lookup,
                metadata_lookup=counted_meta_lookup,
            )
            if not doc.chunk_nodes:  # empty / too-short text
                continue
            if scope.committee and doc.metadata.get("committee") not in scope.committee:
                continue
            out.append(doc)
            if scope.limit and len(out) >= scope.limit:
                break
        if meta_misses:
            _log.warning(
                "document_metadata rows missing for %d URLs — doc_type absent there, "
                "badges derived live; run scripts/enrich_document_metadata.py",
                meta_misses,
            )
        return out
    finally:
        if owned:
            client.close()
