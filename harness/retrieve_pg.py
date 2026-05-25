"""Retrieval façade for the Postgres + pgvector narrative corpus.

This module mirrors the public surface of ``harness/retrieve.py``:

    RetrievalConfigPG          — drop-in replacement for RetrievalConfig
    PrefilterConfig            — SQL-level pre-filter (committee, topic, date)
    TraversalConfig            — link-graph traversal mode + bounds
    RetrievalResult            — same shape as harness.retrieve.RetrievalResult
    retrieve_with_config_pg    — single entry point (filled in by NARR-016+)
    build_retrieve_fn_pg       — factory for the workflow callable (NARR-018)

NARR-015 lands the scaffolding (config dataclasses + YAML round-trip). The
actual dense / BM25 / hybrid / traversal implementations arrive in
NARR-016 → NARR-019. ``retrieve_with_config_pg`` raises ``NotImplementedError``
for now so callers fail loudly until those tasks complete.

YAML shape (extension of the existing ``retrieval:`` block)::

    retrieval:
      mode: hybrid                  # dense | bm25 | hybrid
      k: 10
      prefilter:
        topic_path_prefix: "/en/medicines/"
        committee: ["CHMP", "PRAC"]
        date_range: ["2020-01-01", "2024-12-31"]
      traversal:
        mode: auto                  # none | auto | agent_tool
        max_hops: 1
        link_types: ["hyperlink", "reference_number"]
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from llama_index.core.settings import Settings

from harness.pg import queries as Q
from harness.pg.adapter import row_to_result
from harness.pg.conn import get_pool
from harness.providers import configure_embed_model

_log = logging.getLogger(__name__)

# (chunk_id, score, metadata) — same tuple shape as harness.retrieve.RetrievalResult
# so workflow code that already consumes RetrievalResult can read either path.
RetrievalResult = tuple[str, float, dict[str, Any]]

_RRF_K = 60  # standard RRF constant (Cormack et al. 2009); matches harness.retrieve

RetrieverMode = Literal["dense", "bm25", "hybrid"]
TraversalMode = Literal["none", "auto", "agent_tool"]

# Link types that may appear in the ``links`` table; matches link_extractor.LinkType.
LinkType = Literal["hyperlink", "reference_number", "see_qa"]
_DEFAULT_LINK_TYPES: tuple[str, ...] = ("hyperlink", "reference_number")


def _parse_date(value: Any) -> datetime | None:
    """Parse ISO date or datetime string; return tz-aware datetime (UTC) or None.

    Accepts ``datetime`` and ``date`` instances unchanged (date promoted to UTC
    midnight). Strings are parsed via ``datetime.fromisoformat`` with a Z-suffix
    fallback. None / empty returns None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Allow plain YYYY-MM-DD
            try:
                dt = datetime.strptime(s, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"unparseable date: {value!r}") from exc
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    raise TypeError(f"unsupported date type: {type(value).__name__}")


@dataclass
class PrefilterConfig:
    """SQL ``WHERE`` clauses applied before the ANN / BM25 ranking.

    Empty defaults disable each filter. Concrete SQL composition is the job
    of the retrievers in NARR-016 / NARR-017.
    """
    topic_path_prefix: str | None = None
    committee: list[str] = field(default_factory=list)
    date_range: tuple[datetime, datetime] | None = None

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> PrefilterConfig:
        if not cfg:
            return cls()
        dr_raw = cfg.get("date_range")
        date_range: tuple[datetime, datetime] | None = None
        if dr_raw:
            if not isinstance(dr_raw, (list, tuple)) or len(dr_raw) != 2:
                raise ValueError("prefilter.date_range must be a [start, end] pair")
            start = _parse_date(dr_raw[0])
            end = _parse_date(dr_raw[1])
            if start is None or end is None:
                raise ValueError("prefilter.date_range start/end must both be set")
            if start > end:
                raise ValueError("prefilter.date_range start must be <= end")
            date_range = (start, end)
        committee_raw = cfg.get("committee") or []
        if isinstance(committee_raw, str):
            committee_raw = [committee_raw]
        committee = [str(c).strip() for c in committee_raw if str(c).strip()]
        topic = cfg.get("topic_path_prefix") or None
        return cls(
            topic_path_prefix=str(topic) if topic else None,
            committee=committee,
            date_range=date_range,
        )

    @property
    def is_empty(self) -> bool:
        return not (self.topic_path_prefix or self.committee or self.date_range)


@dataclass
class TraversalConfig:
    """Configure the post-retrieval link-graph expansion."""
    mode: TraversalMode = "none"
    max_hops: int = 1
    link_types: list[str] = field(default_factory=lambda: list(_DEFAULT_LINK_TYPES))

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> TraversalConfig:
        if not cfg:
            return cls()
        mode = cfg.get("mode", "none")
        if mode not in ("none", "auto", "agent_tool"):
            raise ValueError(f"traversal.mode must be none|auto|agent_tool, got {mode!r}")
        max_hops = int(cfg.get("max_hops", 1))
        if max_hops < 0:
            raise ValueError("traversal.max_hops must be >= 0")
        link_types_raw = cfg.get("link_types") or list(_DEFAULT_LINK_TYPES)
        if isinstance(link_types_raw, str):
            link_types_raw = [link_types_raw]
        link_types = [str(lt).strip() for lt in link_types_raw if str(lt).strip()]
        return cls(mode=mode, max_hops=max_hops, link_types=link_types)


@dataclass
class RetrievalConfigPG:
    """Unified retrieval config for the pgvector path.

    Workflows (and run_eval YAML) treat this as the public surface; the dense /
    BM25 / hybrid implementations choose how to honour each field.
    """
    mode: RetrieverMode = "hybrid"
    k: int = 10
    prefilter: PrefilterConfig = field(default_factory=PrefilterConfig)
    traversal: TraversalConfig = field(default_factory=TraversalConfig)

    @classmethod
    def from_yaml_section(cls, cfg: dict[str, Any] | None) -> RetrievalConfigPG:
        cfg = cfg or {}
        mode = cfg.get("mode", "hybrid")
        if mode not in ("dense", "bm25", "hybrid"):
            raise ValueError(f"retrieval.mode must be dense|bm25|hybrid, got {mode!r}")
        k = int(cfg.get("k", 10))
        if k <= 0:
            raise ValueError("retrieval.k must be > 0")
        prefilter = PrefilterConfig.from_dict(cfg.get("prefilter"))
        traversal = TraversalConfig.from_dict(cfg.get("traversal"))
        return cls(mode=mode, k=k, prefilter=prefilter, traversal=traversal)


# ---------------------------------------------------------------------------
# Prefilter composition (shared by dense + BM25)
# ---------------------------------------------------------------------------


def _normalise_topic_prefix(prefix: str) -> str:
    """Ensure ``topic_path_prefix`` ends with a SQL LIKE wildcard."""
    return prefix if prefix.endswith("%") else prefix + "%"


def _compose_prefilter_fragments(
    prefilter: PrefilterConfig,
) -> tuple[list[str], dict[str, Any]]:
    """Return (clause_list, params) for the prefilter WHERE conditions.

    The clauses use ``%(name)s`` placeholders so psycopg can bind safely; the
    caller is responsible for joining them with ``AND`` and prefixing with
    either ``WHERE`` (DENSE_KNN) or ``AND`` (BM25 — its template already
    opens with a ``WHERE c.text_tsv @@ ...`` clause).
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if prefilter.topic_path_prefix:
        clauses.append("d.topic_path LIKE %(topic_prefix)s")
        params["topic_prefix"] = _normalise_topic_prefix(prefilter.topic_path_prefix)
    if prefilter.committee:
        clauses.append("d.committee = ANY(%(committee)s)")
        params["committee"] = list(prefilter.committee)
    if prefilter.date_range:
        clauses.append("d.last_updated BETWEEN %(date_start)s AND %(date_end)s")
        params["date_start"] = prefilter.date_range[0]
        params["date_end"] = prefilter.date_range[1]
    return clauses, params


def _compose_dense_prefilter(prefilter: PrefilterConfig) -> tuple[str, dict[str, Any]]:
    clauses, params = _compose_prefilter_fragments(prefilter)
    sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def _compose_bm25_prefilter(prefilter: PrefilterConfig) -> tuple[str, dict[str, Any]]:
    clauses, params = _compose_prefilter_fragments(prefilter)
    sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    return sql, params


# ---------------------------------------------------------------------------
# Query embedding (NARR-016)
# ---------------------------------------------------------------------------


_embed_configured = False


def _query_embedding(query: str) -> list[float]:
    """Embed ``query`` using the configured LlamaIndex embed model.

    Honours the BGE query prefix when the model is HuggingFaceEmbedding —
    LlamaIndex's :meth:`BaseEmbedding.get_query_embedding` applies it.

    We avoid touching ``Settings.embed_model`` before configuring because the
    getter lazily resolves to OpenAI's embedding model when unset, which fails
    when ``llama-index-embeddings-openai`` is not installed.
    """
    global _embed_configured
    if not _embed_configured:
        configure_embed_model()
        _embed_configured = True
    vec = Settings.embed_model.get_query_embedding(query)
    return [float(x) for x in vec]


# ---------------------------------------------------------------------------
# Dense / BM25 / hybrid retrievers (NARR-016, NARR-017, NARR-018)
# ---------------------------------------------------------------------------


def retrieve_dense_pg(
    query: str,
    config: RetrievalConfigPG,
    *,
    pool: Any = None,
) -> list[RetrievalResult]:
    """HNSW kNN over pgvector. Score = 1 - cosine_distance."""
    pool = pool or get_pool()
    qvec = _query_embedding(query)
    prefilter_sql, prefilter_params = _compose_dense_prefilter(config.prefilter)
    sql = Q.DENSE_KNN.format(prefilter=prefilter_sql)
    params = {"qvec": qvec, "k": config.k, **prefilter_params}
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return [row_to_result(cols, row) for row in rows]


def retrieve_bm25_pg(
    query: str,
    config: RetrievalConfigPG,
    *,
    pool: Any = None,
) -> list[RetrievalResult]:
    """Postgres ``ts_rank_cd`` over the generated ``text_tsv`` column."""
    pool = pool or get_pool()
    prefilter_sql, prefilter_params = _compose_bm25_prefilter(config.prefilter)
    sql = Q.BM25.format(prefilter=prefilter_sql)
    params = {"q": query, "k": config.k, **prefilter_params}
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return [row_to_result(cols, row) for row in rows]


def _rrf_fuse(
    ranked_lists: list[list[RetrievalResult]],
    k: int,
) -> list[RetrievalResult]:
    """Reciprocal Rank Fusion across multiple ranked result lists.

    Matches ``harness.retrieve._rrf_fuse`` exactly so the two backends fuse
    with the same constant and the same tiebreak behaviour.
    """
    scores: dict[str, float] = {}
    meta_store: dict[str, dict[str, Any]] = {}
    for ranked in ranked_lists:
        for rank, (chunk_id, _score, metadata) in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            meta_store[chunk_id] = metadata
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [(chunk_id, score, meta_store[chunk_id]) for chunk_id, score in fused]


def retrieve_hybrid_pg(
    query: str,
    config: RetrievalConfigPG,
    *,
    pool: Any = None,
) -> list[RetrievalResult]:
    """RRF fusion of dense + BM25. Runs both retrievers sequentially against
    the same pool (psycopg connections aren't free-threading-safe for HNSW
    queries; parallel execution can be added later if profiling shows it helps).
    """
    dense = retrieve_dense_pg(query, config, pool=pool)
    bm25 = retrieve_bm25_pg(query, config, pool=pool)
    return _rrf_fuse([dense, bm25], config.k)


# ---------------------------------------------------------------------------
# Auto-traversal (NARR-019)
# ---------------------------------------------------------------------------


def _expand_via_links(
    initial: list[RetrievalResult],
    traversal: TraversalConfig,
    *,
    pool: Any = None,
) -> list[RetrievalResult]:
    """Append link-graph neighbours of the initial seeds, deduped by chunk_id.

    Uses :data:`harness.pg.queries.TRAVERSE_LINKS`, which seeds the recursion
    with the initial doc_ids and walks up to ``traversal.max_hops`` hops.
    The seed chunks stay at the front of the returned list (preserving the
    ranker's order); expansion neighbours are appended in row order (one
    representative chunk per visited doc, lowest chunk_index).
    """
    if traversal.max_hops <= 0 or not initial:
        return initial
    pool = pool or get_pool()
    seed_doc_ids = [
        str(meta.get("doc_id")) for _chunk_id, _score, meta in initial if meta.get("doc_id")
    ]
    if not seed_doc_ids:
        return initial
    params = {
        "seed_doc_ids": seed_doc_ids,
        "max_hops": int(traversal.max_hops),
        "link_types": list(traversal.link_types),
    }
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(Q.TRAVERSE_LINKS, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    seen = {chunk_id for chunk_id, _score, _meta in initial}
    expansion: list[RetrievalResult] = []
    for row in rows:
        result = row_to_result(cols, row)
        if result[0] in seen:
            continue
        seen.add(result[0])
        expansion.append(result)
    if expansion:
        _log.debug(
            "auto-traversal: initial=%d expansion=%d (max_hops=%d link_types=%s)",
            len(initial), len(expansion), traversal.max_hops, traversal.link_types,
        )
    return list(initial) + expansion


# ---------------------------------------------------------------------------
# Dispatcher + factory (NARR-018)
# ---------------------------------------------------------------------------


def retrieve_with_config_pg(
    config: RetrievalConfigPG,
    query: str,
    *,
    pool: Any = None,
    embed_model: Any = None,  # noqa: ARG001 — accepted for parity with harness.retrieve
) -> list[RetrievalResult]:
    """Single retrieval entry point for the pgvector path.

    Dispatches on ``config.mode`` (dense / bm25 / hybrid). When
    ``config.traversal.mode == 'auto'`` the initial results are expanded with
    one query against the recursive ``links`` CTE.
    """
    if config.mode == "dense":
        results = retrieve_dense_pg(query, config, pool=pool)
    elif config.mode == "bm25":
        results = retrieve_bm25_pg(query, config, pool=pool)
    elif config.mode == "hybrid":
        results = retrieve_hybrid_pg(query, config, pool=pool)
    else:
        raise ValueError(f"unsupported retrieval mode: {config.mode!r}")

    if config.traversal.mode == "auto":
        results = _expand_via_links(results, config.traversal, pool=pool)
    # mode='agent_tool' is handled by harness/pg/tools.py inside ReAct workflows;
    # retrieve_with_config_pg just returns the seed top-k in that case.
    return results


def build_retrieve_fn_pg(
    config: RetrievalConfigPG,
    *,
    pool: Any = None,
) -> Callable[[str], list[RetrievalResult]]:
    """Return a ``fn(query) -> list[RetrievalResult]`` configured for ``config``.

    Drop-in replacement for ``harness.retrieve.build_retrieve_fn`` — workflows
    can swap which factory they import based on the ``EMA_RETRIEVER`` env var
    (NARR-021 / NARR-022 wire that switch).
    """
    def retrieve_fn(query: str) -> list[RetrievalResult]:
        return retrieve_with_config_pg(config, query, pool=pool)

    return retrieve_fn
