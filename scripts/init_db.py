"""Apply corpus/pg_schema.sql to the configured PG_DSN, idempotently.

Usage:
    python scripts/init_db.py                # CREATE … IF NOT EXISTS
    python scripts/init_db.py --reset        # drop tables first, then create
    python scripts/init_db.py --dsn DSN      # override PG_DSN (e.g. PG_DSN_TEST)
    python scripts/init_db.py --schema PATH  # override schema file path

Exits non-zero if the DDL fails to apply or if any required extension is missing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from config import PG_DSN  # noqa: E402

_DEFAULT_SCHEMA = _REPO_ROOT / "corpus" / "pg_schema.sql"
_DROP_DDL = """
DROP TABLE IF EXISTS links CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
"""


def _verify_extensions(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm')")
    found = {row[0]: row[1] for row in cur.fetchall()}
    missing = {"vector", "pg_trgm"} - set(found)
    if missing:
        raise RuntimeError(f"Missing required extensions: {missing}")
    vec_version = found["vector"]
    if tuple(int(p) for p in vec_version.split(".")[:2]) < (0, 5):
        raise RuntimeError(f"pgvector >= 0.5.0 required (HNSW); found {vec_version}")
    print(f"  pgvector {vec_version}, pg_trgm {found['pg_trgm']}")


def _verify_objects(cur: psycopg.Cursor) -> None:
    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('documents','chunks','links') ORDER BY tablename"
    )
    tables = [row[0] for row in cur.fetchall()]
    expected = ["chunks", "documents", "links"]
    if tables != expected:
        raise RuntimeError(f"Expected tables {expected}; got {tables}")
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname='chunks_embedding_hnsw'")
    if not cur.fetchone():
        raise RuntimeError("Missing HNSW index chunks_embedding_hnsw")
    cur.execute(
        "SELECT attname FROM pg_attribute "
        "WHERE attrelid='chunks'::regclass AND attname='text_tsv' AND NOT attisdropped"
    )
    if not cur.fetchone():
        raise RuntimeError("Missing tsvector column chunks.text_tsv")
    print(f"  tables: {', '.join(tables)}")
    print("  hnsw index + tsvector column present")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pg_schema.sql idempotently.")
    parser.add_argument("--reset", action="store_true", help="drop documents/chunks/links before applying")
    parser.add_argument("--dsn", default=None, help="override PG_DSN")
    parser.add_argument("--schema", default=str(_DEFAULT_SCHEMA), help="path to schema SQL file")
    args = parser.parse_args()

    dsn = args.dsn or PG_DSN
    schema_path = Path(args.schema)
    if not schema_path.exists():
        raise SystemExit(f"Schema file not found: {schema_path}")
    ddl = schema_path.read_text()

    safe_dsn = dsn.split("@", 1)[-1] if "@" in dsn else dsn
    print(f"Applying schema to {safe_dsn}")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if args.reset:
                print("  resetting (DROP TABLE IF EXISTS …)")
                cur.execute(_DROP_DDL)
            cur.execute(ddl)
        conn.commit()
        with conn.cursor() as cur:
            _verify_extensions(cur)
            _verify_objects(cur)

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
