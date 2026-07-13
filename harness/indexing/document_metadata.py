"""Canonical per-URL document labels — Mongo ``document_metadata`` collection.

The EMA-published labels (``doc_type`` from the website-data JSON export,
``audience``/``site_topic`` from the page badges) are *derived facts about a
URL*, independent of any parser run — so they get their own collection instead
of living on ``parsed_documents`` rows (keyed per parser) or only on the Neo4j
graph (lost on rebuild). One row per URL:

    { url, doc_id,                       # doc_id = sha256(url), the graph join key
      doc_type,                          # EMA JSON export "type" (PDFs; 85 values)
      audience, site_topic,              # ema-bg-* page badges (HTML pages)
      provenance: { doc_type: {source, stamped_at},
                    badges:   {source, stamped_at} } }

Producers: ``scripts/enrich_document_metadata.py`` (re-runnable after each
scrape). Consumers: ``harness.indexing.ingest`` joins the row at ingest so new
graph builds stamp all three labels on ``:Document`` nodes;
``scripts/propagate_metadata_to_graph.py`` patches an existing graph without a
rebuild. The two label groups are upserted independently (field-scoped ``$set``)
so the badge pass and the doc_type pass compose on the same row in any order.

Provenance carries the stamp time per label group — the JSON export and the
scrape snapshot drift independently, and a stale label should be datable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient, UpdateOne

from config import MONGO_DB, MONGO_URI
from harness.indexing.chunking import doc_id_for

COLLECTION = "document_metadata"
URL_INDEX_NAME = "url_uniq"
DOC_ID_INDEX_NAME = "doc_id_idx"

#: ``url -> row`` fetch used by ingest to join labels onto an IngestedDoc.
MetadataLookup = Callable[[str], dict[str, Any] | None]

_BADGE_SOURCE = "web_items.html_raw"
_DOC_TYPE_SOURCE = "ema_json_export"


def _collection(client: MongoClient[Any]) -> Any:
    return client[MONGO_DB][COLLECTION]


def bootstrap_indexes(client: MongoClient[Any] | None = None) -> None:
    """Create the unique-URL + doc_id indexes (idempotent)."""
    owned = client is None
    c: MongoClient[Any] = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    try:
        col = _collection(c)
        col.create_index([("url", 1)], unique=True, name=URL_INDEX_NAME)
        col.create_index([("doc_id", 1)], name=DOC_ID_INDEX_NAME)
    finally:
        if owned:
            c.close()


def _flush(col: Any, ops: list[UpdateOne]) -> int:
    if not ops:
        return 0
    col.bulk_write(ops, ordered=False)
    return len(ops)


def upsert_badges(
    rows: Iterable[Mapping[str, Any]],
    *,
    client: MongoClient[Any] | None = None,
    stamped_at: datetime | None = None,
    batch_size: int = 1000,
) -> int:
    """Upsert badge labels; each row is ``{url, audience, site_topic}``.

    ``audience``/``site_topic`` may be None (page has no badge) — the null is
    written deliberately, so a page that *lost* its badge on a re-scrape is
    cleared rather than left stale. Returns the number of rows written.
    """
    owned = client is None
    c: MongoClient[Any] = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    at = stamped_at or datetime.now(UTC)
    written = 0
    try:
        col = _collection(c)
        ops: list[UpdateOne] = []
        for row in rows:
            url = row["url"]
            ops.append(
                UpdateOne(
                    {"url": url},
                    {
                        "$set": {
                            "doc_id": doc_id_for(url),
                            "audience": row.get("audience"),
                            "site_topic": row.get("site_topic"),
                            "provenance.badges": {"source": _BADGE_SOURCE, "stamped_at": at},
                        }
                    },
                    upsert=True,
                )
            )
            if len(ops) >= batch_size:
                written += _flush(col, ops)
                ops = []
        written += _flush(col, ops)
        return written
    finally:
        if owned:
            c.close()


def upsert_doc_types(
    url_to_type: Mapping[str, str],
    *,
    client: MongoClient[Any] | None = None,
    stamped_at: datetime | None = None,
    batch_size: int = 1000,
) -> int:
    """Upsert ``doc_type`` per URL from the parsed EMA JSON export.

    Rows are written for *every* export entry (not just currently-indexed
    docs) — the collection is the canonical label store, so future scrapes
    join instantly. Returns the number of rows written.
    """
    owned = client is None
    c: MongoClient[Any] = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    at = stamped_at or datetime.now(UTC)
    written = 0
    try:
        col = _collection(c)
        ops: list[UpdateOne] = []
        for url, doc_type in url_to_type.items():
            ops.append(
                UpdateOne(
                    {"url": url},
                    {
                        "$set": {
                            "doc_id": doc_id_for(url),
                            "doc_type": doc_type or None,
                            "provenance.doc_type": {
                                "source": _DOC_TYPE_SOURCE,
                                "stamped_at": at,
                            },
                        }
                    },
                    upsert=True,
                )
            )
            if len(ops) >= batch_size:
                written += _flush(col, ops)
                ops = []
        written += _flush(col, ops)
        return written
    finally:
        if owned:
            c.close()


def mongo_metadata_lookup(client: MongoClient[Any]) -> MetadataLookup:
    """A ``url -> document_metadata row`` fetch (None when not enriched)."""
    col = _collection(client)

    def _lookup(url: str) -> dict[str, Any] | None:
        return col.find_one({"url": url})

    return _lookup
