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
from datetime import UTC, datetime
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
from harness.indexing.parser_preference import PreferenceEntry, load_parser_preference
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
        # Topic-subgraph membership (scripts/manage_topic_hubs.py build) rides
        # the same join, so a graph rebuild keeps the stamps.
        metadata["topic_hubs"] = meta_row.get("topic_hubs") or None
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


@dataclass(frozen=True)
class SourceChoice:
    """The row the build uses for one URL, and the row the rule before 2026-11-25 used.

    ``old_rule`` is the first clean row the cursor yielded for the URL. Until
    2026-11-25 the build kept exactly that row, and the 79,882 documents in the graph
    were built from it. A graph document that records no parse identity yet counts as
    built from ``old_rule`` (proposal ``docs/next/pipeline_refresh.md``).
    """

    selected: dict[str, Any]
    old_rule: dict[str, Any]
    fallback: bool = False  # True: no preference entry matched (decision F)


@dataclass
class SelectionStats:
    """Counts of one selection pass, for the log line at its end."""

    urls: int = 0
    fallbacks: int = 0


def preference_key(content_type: str | None) -> str | None:
    """The preference-file key of a row: the same pdf/html test the build has always used."""
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "application/pdf"
    if "html" in ct:
        return "text/html"
    return None


_OLDEST = datetime.min.replace(tzinfo=UTC)


def _parsed_at(row: dict[str, Any]) -> datetime:
    value = row.get("parsed_at")
    if not isinstance(value, datetime):
        return _OLDEST
    # pymongo returns naive UTC datetimes; a test may insert aware ones.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _newest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Newest ``parsed_at``; a tie goes to the later ``_id`` (ObjectIds sort by time)."""
    return max(rows, key=lambda r: (_parsed_at(r), str(r.get("_id", ""))))


def select_row(
    rows: list[dict[str, Any]], preference: dict[str, list[PreferenceEntry]]
) -> tuple[dict[str, Any], bool]:
    """Pick one of the clean rows of one URL. Returns ``(row, fell_back)``.

    The row that matches the earliest preference entry wins; among rows that match
    the same entry, the newest. Before 2026-11-25 the build kept the first row in
    cursor order, which nothing defined: a re-parse never replaced an older row.
    When no entry matches, the newest clean row is used and ``fell_back`` is True
    (decision F, ``docs/pm/decisions/2026-11-25_unlisted-parser.md``).
    """
    key = preference_key(rows[0].get("content_type"))
    for entry in preference.get(key or "", []):
        matching = [r for r in rows if entry.matches(r.get("parser"), r.get("parser_version"))]
        if matching:
            return _newest(matching), False
    return _newest(rows), True


def _url_groups(cursor: Any) -> Iterator[list[dict[str, Any]]]:
    """Group the clean pdf/html rows of a cursor sorted by URL: one list per URL."""
    group: list[dict[str, Any]] = []
    for row in cursor:
        url = row.get("url")
        if not url or preference_key(row.get("content_type")) is None:
            continue
        if group and group[0]["url"] != url:
            yield group
            group = []
        group.append(row)
    if group:
        yield group


def iter_source_groups(
    scope: ScopeConfig,
    *,
    client: MongoClient[Any],
    preference: dict[str, list[PreferenceEntry]] | None = None,
    stats: SelectionStats | None = None,
) -> Iterator[SourceChoice]:
    """Yield one :class:`SourceChoice` per URL, honouring the scope.

    URL-level filters (topic_prefix, limit) are applied here; the committee filter
    needs parsed text, so it is applied after metadata derivation. ``preference``
    defaults to ``harness/configs/parser_preference.yaml``.
    """
    pref = preference if preference is not None else load_parser_preference()
    stats = stats if stats is not None else SelectionStats()
    col = client[MONGO_DB][PARSED_COLLECTION]
    yielded = 0
    # no_cursor_timeout: this cursor is iterated across a multi-hour embed pass and
    # a slower link-extraction pass; the server's default 10-min idle timeout can
    # expire it mid-iteration (CursorNotFound, code 43). Close it explicitly in the
    # finally so the server-side cursor is not leaked. The sort by URL keeps the rows
    # of one URL adjacent, so selection needs no second query.
    cursor = col.find({"error": ""}, no_cursor_timeout=True).sort("url", 1)
    try:
        for rows in _url_groups(cursor):
            url = rows[0]["url"]
            if scope.topic_prefix and not _matches_topic(url_metadata(url).topic_path, scope.topic_prefix):
                continue
            row, fell_back = select_row(rows, pref)
            stats.urls += 1
            if fell_back:
                stats.fallbacks += 1
                _log.warning(
                    "no parser preference entry matches the rows of %s (%s); using the newest clean row",
                    url, ", ".join(f"{r.get('parser')}@{r.get('parser_version')}" for r in rows),
                )
            yield SourceChoice(selected=row, old_rule=rows[0], fallback=fell_back)
            yielded += 1
            # Over-fetch slightly when a committee filter will prune later.
            if scope.limit and not scope.committee and yielded >= scope.limit:
                return
    finally:
        cursor.close()
        if stats.fallbacks:
            _log.warning(
                "%d of %d URLs had no row from a listed parser and used their newest clean row "
                "(harness/configs/parser_preference.yaml)", stats.fallbacks, stats.urls,
            )


def iter_source_rows(
    scope: ScopeConfig,
    *,
    client: MongoClient[Any],
    preference: dict[str, list[PreferenceEntry]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield the selected clean ``parsed_documents`` row of each URL (see :func:`iter_source_groups`)."""
    for choice in iter_source_groups(scope, client=client, preference=preference):
        yield choice.selected


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
