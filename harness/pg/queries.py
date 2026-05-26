"""Parameterised SQL string constants used by ingest + retrieval.

Logic lives in the modules that consume these; this file is intentionally
just constants so the schema-shape stays in one place and parameter binding
is consistent.

Conventions:
    * Use `$N`-style placeholders only where psycopg specifically requires it
      (recursive CTE binding). All other queries use `%s` and `%(name)s`.
    * Filter clauses that are *optional* are formatted in at execute time
      (e.g. `_DENSE_PREFILTER_FRAGMENT`) — the consumer assembles them with
      `psycopg.sql.SQL.format` against `Identifier` / `Literal` where dynamic
      identifiers are needed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

UPSERT_DOCUMENT = """
INSERT INTO documents (
    doc_id, source_url, source_type, title, topic_path,
    reference_number, committee, revision, last_updated, raw_byte_size,
    parser, parser_version, parsed_at, parsed_text, parsed_text_hash,
    meta
)
VALUES (
    %(doc_id)s, %(source_url)s, %(source_type)s, %(title)s, %(topic_path)s,
    %(reference_number)s, %(committee)s, %(revision)s, %(last_updated)s,
    %(raw_byte_size)s,
    %(parser)s, %(parser_version)s, %(parsed_at)s, %(parsed_text)s, %(parsed_text_hash)s,
    %(meta)s
)
ON CONFLICT (doc_id) DO UPDATE SET
    title            = EXCLUDED.title,
    topic_path       = EXCLUDED.topic_path,
    reference_number = EXCLUDED.reference_number,
    committee        = EXCLUDED.committee,
    revision         = EXCLUDED.revision,
    last_updated     = EXCLUDED.last_updated,
    raw_byte_size    = EXCLUDED.raw_byte_size,
    parser           = EXCLUDED.parser,
    parser_version   = EXCLUDED.parser_version,
    parsed_at        = EXCLUDED.parsed_at,
    parsed_text      = EXCLUDED.parsed_text,
    parsed_text_hash = EXCLUDED.parsed_text_hash,
    meta             = EXCLUDED.meta
"""

# Returns (doc_id, parsed_text_hash) for the given doc_ids — drives the
# hash-skip path in harness.embed_pg.sync().
PARSED_HASH_BY_DOC_IDS = (
    "SELECT doc_id, parsed_text_hash FROM documents "
    "WHERE doc_id = ANY(%(doc_ids)s)"
)

INSERT_CHUNK = """
INSERT INTO chunks (
    chunk_id, doc_id, chunk_index, text, heading_path, token_count, embedding
)
VALUES (
    %(chunk_id)s, %(doc_id)s, %(chunk_index)s, %(text)s,
    %(heading_path)s, %(token_count)s, %(embedding)s
)
ON CONFLICT (chunk_id) DO NOTHING
"""

INSERT_LINK = """
INSERT INTO links (
    src_doc_id, tgt_url, tgt_doc_id, link_type, anchor, chunk_id
)
VALUES (
    %(src_doc_id)s, %(tgt_url)s, %(tgt_doc_id)s, %(link_type)s,
    %(anchor)s, %(chunk_id)s
)
ON CONFLICT (src_doc_id, tgt_url, link_type) DO NOTHING
"""

DELETE_CHUNKS_BY_DOC = "DELETE FROM chunks WHERE doc_id = ANY(%(doc_ids)s)"
DELETE_LINKS_BY_DOC = "DELETE FROM links WHERE src_doc_id = ANY(%(doc_ids)s)"

DOC_IDS_BY_SOURCE_URLS = "SELECT doc_id FROM documents WHERE source_url = ANY(%(source_urls)s)"

# ---------------------------------------------------------------------------
# Retrieval — dense
# ---------------------------------------------------------------------------

# The {prefilter} placeholder is replaced with a fragment built from
# PrefilterConfig (or left empty). Joins documents for metadata.
DENSE_KNN = """
SELECT
    c.chunk_id,
    c.doc_id,
    c.chunk_index,
    c.text,
    c.heading_path,
    c.token_count,
    d.source_url,
    d.source_type,
    d.title,
    d.topic_path,
    d.reference_number,
    d.committee,
    d.revision,
    d.last_updated,
    1.0 - (c.embedding <=> %(qvec)s::vector) AS score
FROM chunks c
JOIN documents d USING (doc_id)
{prefilter}
ORDER BY c.embedding <=> %(qvec)s::vector
LIMIT %(k)s
"""

# ---------------------------------------------------------------------------
# Retrieval — BM25 (tsvector)
# ---------------------------------------------------------------------------

BM25 = """
SELECT
    c.chunk_id,
    c.doc_id,
    c.chunk_index,
    c.text,
    c.heading_path,
    c.token_count,
    d.source_url,
    d.source_type,
    d.title,
    d.topic_path,
    d.reference_number,
    d.committee,
    d.revision,
    d.last_updated,
    ts_rank_cd(c.text_tsv, plainto_tsquery('english', %(q)s)) AS score
FROM chunks c
JOIN documents d USING (doc_id)
WHERE c.text_tsv @@ plainto_tsquery('english', %(q)s)
{prefilter}
ORDER BY score DESC
LIMIT %(k)s
"""

# ---------------------------------------------------------------------------
# Retrieval — fetch a single chunk by id (for adapter.get_node_by_id)
# ---------------------------------------------------------------------------

CHUNK_BY_ID = """
SELECT
    c.chunk_id,
    c.doc_id,
    c.chunk_index,
    c.text,
    c.heading_path,
    c.token_count,
    d.source_url,
    d.source_type,
    d.title,
    d.topic_path,
    d.reference_number,
    d.committee,
    d.revision,
    d.last_updated
FROM chunks c
JOIN documents d USING (doc_id)
WHERE c.chunk_id = %(chunk_id)s
"""

# ---------------------------------------------------------------------------
# Retrieval — auto-traversal (recursive CTE over links)
# ---------------------------------------------------------------------------

# Seeds the recursion with %(seed_doc_ids)s, walks up to %(max_hops)s,
# restricts to link_types in %(link_types)s, returns one representative
# chunk per visited doc (the lowest chunk_index, deterministic).
TRAVERSE_LINKS = """
WITH RECURSIVE walk AS (
    SELECT
        unnest(%(seed_doc_ids)s::text[]) AS doc_id,
        0::int AS hop
    UNION ALL
    SELECT
        l.tgt_doc_id AS doc_id,
        walk.hop + 1 AS hop
    FROM walk
    JOIN links l ON l.src_doc_id = walk.doc_id
    WHERE walk.hop < %(max_hops)s
      AND l.tgt_doc_id IS NOT NULL
      AND l.link_type = ANY(%(link_types)s)
),
visited AS (
    SELECT DISTINCT doc_id FROM walk WHERE doc_id IS NOT NULL
),
representative AS (
    SELECT DISTINCT ON (c.doc_id)
        c.chunk_id, c.doc_id, c.chunk_index, c.text, c.heading_path, c.token_count
    FROM chunks c
    JOIN visited v ON v.doc_id = c.doc_id
    ORDER BY c.doc_id, c.chunk_index
)
SELECT
    r.chunk_id,
    r.doc_id,
    r.chunk_index,
    r.text,
    r.heading_path,
    r.token_count,
    d.source_url,
    d.source_type,
    d.title,
    d.topic_path,
    d.reference_number,
    d.committee,
    d.revision,
    d.last_updated,
    0.0::float AS score
FROM representative r
JOIN documents d USING (doc_id)
WHERE r.doc_id <> ALL(%(seed_doc_ids)s::text[])
"""

# ---------------------------------------------------------------------------
# Link resolution (scripts/resolve_links.py)
# ---------------------------------------------------------------------------

RESOLVE_LINKS_BY_URL = """
UPDATE links l
SET    tgt_doc_id = d.doc_id
FROM   documents d
WHERE  l.tgt_doc_id IS NULL
  AND  l.link_type = 'hyperlink'
  AND  d.source_url = l.tgt_url
"""

RESOLVE_LINKS_BY_REFERENCE = """
UPDATE links l
SET    tgt_doc_id = d.doc_id
FROM   documents d
WHERE  l.tgt_doc_id IS NULL
  AND  l.link_type = 'reference_number'
  AND  d.reference_number = l.tgt_url
"""

UNRESOLVED_LINKS_SAMPLE = """
SELECT link_type, tgt_url, COUNT(*) AS n
FROM   links
WHERE  tgt_doc_id IS NULL
GROUP BY link_type, tgt_url
ORDER BY n DESC
LIMIT %(limit)s
"""
