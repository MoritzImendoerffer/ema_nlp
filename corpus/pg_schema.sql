-- ema_nlp pgvector narrative-corpus schema (NARR-002)
-- All statements are idempotent: safe to re-run.
-- scripts/init_db.py applies this file.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

------------------------------------------------------------------------------
-- documents: one row per source URL
-- parser/parser_version/parsed_at/parsed_text/parsed_text_hash added MIGR-006
-- (Mongo `parsed_documents` row that produced this PG row + content hash for
--  idempotent re-sync).
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    doc_id           TEXT PRIMARY KEY,                        -- sha256(source_url)
    source_url       TEXT UNIQUE NOT NULL,
    source_type      TEXT NOT NULL CHECK (source_type IN ('pdf','html')),
    title            TEXT,
    topic_path       TEXT,                                    -- derived from URL path
    reference_number TEXT,                                    -- EMA/.../YYYY when found
    committee        TEXT,                                    -- CHMP/PRAC/CVMP/COMP/PDCO/CAT — parsed from reference_number
    revision         TEXT,
    last_updated     TIMESTAMPTZ,
    raw_byte_size    INT,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    parser           TEXT,                                    -- e.g. 'pymupdf4llm', 'trafilatura'
    parser_version   TEXT,
    parsed_at        TIMESTAMPTZ,                             -- when the parser ran (Mongo parsed_documents.parsed_at)
    parsed_text      TEXT,                                    -- full pre-chunk text from the parser
    parsed_text_hash TEXT,                                    -- sha256(parsed_text) — drives the sync hash-skip path
    meta             JSONB NOT NULL DEFAULT '{}'              -- escape hatch
);

-- Idempotent column adds for already-populated DBs (existing rows get NULLs
-- in the new columns until the next sync run).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parser           TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parser_version   TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parsed_at        TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parsed_text      TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parsed_text_hash TEXT;

CREATE INDEX IF NOT EXISTS documents_topic_path_idx  ON documents (topic_path);
CREATE INDEX IF NOT EXISTS documents_reference_idx   ON documents (reference_number);
CREATE INDEX IF NOT EXISTS documents_committee_idx   ON documents (committee);
CREATE INDEX IF NOT EXISTS documents_last_updated    ON documents (last_updated);
CREATE INDEX IF NOT EXISTS documents_title_trgm      ON documents USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS documents_parser_idx      ON documents (parser, parser_version);

------------------------------------------------------------------------------
-- chunks: one row per text chunk; HNSW on embedding, GIN on tsvector
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,                            -- sha256(doc_id || chunk_index || text)
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  INT  NOT NULL,
    text         TEXT NOT NULL,
    heading_path TEXT,                                        -- e.g. "## 2. What is..."
    token_count  INT,
    embedding    vector(1024) NOT NULL,
    text_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_doc_id_idx     ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_text_tsv_idx   ON chunks USING gin (text_tsv);

------------------------------------------------------------------------------
-- links: edges between documents; tgt_doc_id filled by scripts/resolve_links.py
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS links (
    src_doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    tgt_url    TEXT NOT NULL,                                 -- raw target, may not resolve
    tgt_doc_id TEXT REFERENCES documents(doc_id),             -- nullable until resolved
    link_type  TEXT NOT NULL,                                 -- 'hyperlink' | 'reference_number' | 'see_qa'
    anchor     TEXT,
    chunk_id   TEXT REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    PRIMARY KEY (src_doc_id, tgt_url, link_type)
);

CREATE INDEX IF NOT EXISTS links_tgt_doc_idx ON links (tgt_doc_id);
CREATE INDEX IF NOT EXISTS links_link_type   ON links (link_type);
CREATE INDEX IF NOT EXISTS links_chunk_idx   ON links (chunk_id);
