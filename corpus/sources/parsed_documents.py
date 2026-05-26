"""Mongo writer + index bootstrap for the ``parsed_documents`` collection.

``parsed_documents`` is the parsed-output sink for every parser under
``corpus/parsers/``. The compound unique key is ``(url, parser, parser_version)``
— different parsers can coexist for the same URL, and different versions of
the same parser coexist until the operator chooses to retire one.

Two public entry points:

    write_parsed_document(doc, *, client=None)
        Single-doc upsert via ``bulk_write([UpdateOne(...)], upsert=True)``.
        Returns ``{matched, modified, upserted}`` counts. Raises
        ``ValueError`` before touching Mongo if ``doc`` isn't a valid
        ``ParsedDocument`` (covers caller mutation after construction too).

    bootstrap_indexes(client=None)
        Idempotently create the unique compound index plus the per-URL
        and per-parser selection indexes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.operations import UpdateOne

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import MONGO_DB, MONGO_URI  # noqa: E402
from corpus.parsers.base import ParsedDocument, _validate  # noqa: E402

COLLECTION = "parsed_documents"
UNIQUE_INDEX_NAME = "url_parser_version_uniq"
URL_INDEX_NAME = "url_idx"
PARSER_INDEX_NAME = "parser_idx"


def _collection(client: MongoClient[Any]) -> Collection[Any]:
    return client[MONGO_DB][COLLECTION]


def bootstrap_indexes(client: MongoClient[Any] | None = None) -> None:
    """Create the compound unique key + supporting indexes (idempotent)."""
    owned = client is None
    c: MongoClient[Any] = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    try:
        col = _collection(c)
        col.create_index(
            [("url", 1), ("parser", 1), ("parser_version", 1)],
            unique=True,
            name=UNIQUE_INDEX_NAME,
        )
        col.create_index([("url", 1)], name=URL_INDEX_NAME)
        col.create_index(
            [("parser", 1), ("parser_version", 1)],
            name=PARSER_INDEX_NAME,
        )
    finally:
        if owned:
            c.close()


def write_parsed_document(
    doc: ParsedDocument,
    *,
    client: MongoClient[Any] | None = None,
) -> dict[str, int]:
    """Upsert a single ParsedDocument keyed on ``(url, parser, parser_version)``.

    Raises ``ValueError`` for malformed input *before* touching Mongo.
    """
    if not isinstance(doc, ParsedDocument):
        raise ValueError(
            f"write_parsed_document expects ParsedDocument, got {type(doc).__name__}"
        )
    # Defensive re-validation: catches mutation after construction.
    _validate(doc)

    owned = client is None
    c: MongoClient[Any] = MongoClient(MONGO_URI) if owned else client  # type: ignore[assignment]
    try:
        col = _collection(c)
        op = UpdateOne(
            {
                "url": doc.url,
                "parser": doc.parser,
                "parser_version": doc.parser_version,
            },
            {"$set": doc.to_mongo()},
            upsert=True,
        )
        result = col.bulk_write([op], ordered=True)
        return {
            "matched": int(result.matched_count or 0),
            "modified": int(result.modified_count or 0),
            "upserted": int(len(result.upserted_ids or {})),
        }
    finally:
        if owned:
            c.close()
