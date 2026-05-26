"""
Legacy retrieval façade — FAISS over the Q&A `corpus.jsonl`.

NARR-028 (2026-05-26) flipped the runtime default to the pgvector path in
`harness.retrieve_pg`; this module remains available behind
``EMA_RETRIEVER=faiss`` for back-compat experiments and benchmark-only
runs. New retrieval features should go into `harness.retrieve_pg`.

Three base modes (selectable at call time):
  "dense"  (A0)  — VectorStoreIndex similarity search only
  "bm25"         — BM25 keyword search only (rank-bm25 via llama-index-retrievers-bm25)
  "hybrid" (A0+) — Reciprocal Rank Fusion of dense + BM25

Four retrieval strategies (selectable via RetrievalConfig):
  "flat"         — standard flat retrieval (default; uses the base mode above)
  "recursive"    — flat retrieval + automatic cross_ref expansion (N hops)
  "hierarchical" — two-level page → Q&A retrieval (requires hierarchical index)
  "agentic"      — delegated to a ReAct/CRAG agent via the chain registry

All retrieve functions return a uniform list of (qa_id, score, metadata) triples
where metadata includes at minimum: qa_id, topic_path, source_url, source_type, cross_refs.

RRF is implemented directly (no LLM required) using the standard formula:
  RRF(d) = Σ_r  1 / (RRF_K + rank_r(d))
with RRF_K = 60 (Cormack et al. 2009).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from llama_index.core import VectorStoreIndex
from llama_index.retrievers.bm25 import BM25Retriever

log = logging.getLogger(__name__)

RetrieverMode = Literal["dense", "bm25", "hybrid"]
RetrievalStrategyId = Literal["flat", "recursive", "hierarchical", "agentic"]

# (qa_id, normalised_score, node_metadata)
RetrievalResult = tuple[str, float, dict]

_RRF_K = 60  # standard RRF constant

# BM25 index build is O(n_docs * avg_doc_len) and takes ~1 s for 26k records.
# Cache per (index identity, k) so each session builds it at most once.
_bm25_cache: dict[tuple[int, int], BM25Retriever] = {}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RecursiveConfig:
    max_hops: int = 1


@dataclass
class HierarchicalConfig:
    top_doc_k: int = 5
    summary_index_dir: str | None = None


@dataclass
class RetrievalConfig:
    """
    Unified retrieval configuration — read from the ``retrieval:`` YAML section.

    All fields have sensible defaults so existing configs continue to work without
    specifying a ``strategy`` key.

    Attributes:
        strategy:    "flat" | "recursive" | "hierarchical" | "agentic"
        mode:        "dense" | "bm25" | "hybrid"  (applies to flat + recursive)
        k:           Number of results to return
        recursive:   Sub-config for the recursive strategy
        hierarchical: Sub-config for the hierarchical strategy

    Example YAML::

        retrieval:
          strategy: recursive
          mode: hybrid
          k: 10
          recursive:
            max_hops: 1
    """
    strategy: RetrievalStrategyId = "flat"
    mode: RetrieverMode = "hybrid"
    k: int = 10
    recursive: RecursiveConfig = field(default_factory=RecursiveConfig)
    hierarchical: HierarchicalConfig = field(default_factory=HierarchicalConfig)

    @classmethod
    def from_yaml_section(cls, cfg: dict) -> "RetrievalConfig":
        """Build a RetrievalConfig from the ``retrieval:`` dict in a run YAML."""
        rec_cfg = RecursiveConfig(**cfg.get("recursive", {}))
        hier_raw = cfg.get("hierarchical", {})
        hier_cfg = HierarchicalConfig(
            top_doc_k=hier_raw.get("top_doc_k", 5),
            summary_index_dir=hier_raw.get("summary_index_dir"),
        )
        return cls(
            strategy=cfg.get("strategy", "flat"),
            mode=cfg.get("mode", "hybrid"),
            k=cfg.get("k", 10),
            recursive=rec_cfg,
            hierarchical=hier_cfg,
        )


# ---------------------------------------------------------------------------
# Low-level primitives
# ---------------------------------------------------------------------------

def _results_from_nodes(nodes_with_scores) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    for nws in nodes_with_scores:
        node = nws.node
        qa_id = node.metadata.get("qa_id", node.node_id)
        score = float(nws.score or 0.0)
        results.append((qa_id, score, dict(node.metadata)))
    return results


def make_dense_retriever(index: VectorStoreIndex, k: int, embed_model=None):
    """Return a LlamaIndex dense retriever from the given VectorStoreIndex."""
    kwargs: dict = {"similarity_top_k": k}
    if embed_model is not None:
        kwargs["embed_model"] = embed_model
    return index.as_retriever(**kwargs)


def make_bm25_retriever(index: VectorStoreIndex, k: int) -> BM25Retriever:
    """Return a BM25Retriever built from the docstore (cached per session)."""
    key = (id(index), k)
    if key not in _bm25_cache:
        _bm25_cache[key] = BM25Retriever.from_defaults(
            docstore=index.docstore,
            similarity_top_k=k,
        )
    return _bm25_cache[key]


def _rrf_fuse(
    ranked_lists: list[list[RetrievalResult]],
    k: int,
) -> list[RetrievalResult]:
    """
    Reciprocal Rank Fusion over multiple ranked result lists.

    Each list is a list of (qa_id, score, metadata) already ordered by rank.
    Returns a new ranked list of length ≤ k, ordered by descending RRF score.
    """
    rrf_scores: dict[str, float] = {}
    metadata_store: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, (qa_id, _score, meta) in enumerate(ranked):
            rrf_scores[qa_id] = rrf_scores.get(qa_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            metadata_store[qa_id] = meta

    fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [(qa_id, score, metadata_store[qa_id]) for qa_id, score in fused]


def retrieve(
    index: VectorStoreIndex,
    query: str,
    *,
    mode: RetrieverMode = "hybrid",
    k: int = 10,
    embed_model=None,
) -> list[RetrievalResult]:
    """
    Retrieve the top-k Q&A nodes for *query* using the selected *mode*.

    Args:
        index:       VectorStoreIndex built by harness.embed.build_index.
        query:       Natural-language query string.
        mode:        "dense" | "bm25" | "hybrid"
        k:           Number of results to return.
        embed_model: Override the embedding model (used in tests).

    Returns:
        Ordered list of (qa_id, score, metadata) — highest score first.
        For "hybrid" the score is the RRF fused score (higher = better).
    """
    if mode == "dense":
        retriever = make_dense_retriever(index, k, embed_model)
        nodes = retriever.retrieve(query)
        return _results_from_nodes(nodes)

    if mode == "bm25":
        retriever = make_bm25_retriever(index, k)
        nodes = retriever.retrieve(query)
        return _results_from_nodes(nodes)

    # hybrid: RRF fusion of dense + BM25 (no LLM required)
    dense_results = _results_from_nodes(make_dense_retriever(index, k, embed_model).retrieve(query))
    bm25_results = _results_from_nodes(make_bm25_retriever(index, k).retrieve(query))
    return _rrf_fuse([dense_results, bm25_results], k)


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _retrieve_recursive(
    index: VectorStoreIndex,
    query: str,
    *,
    mode: RetrieverMode,
    k: int,
    max_hops: int,
    embed_model=None,
) -> list[RetrievalResult]:
    """
    Flat retrieval followed by automatic cross_ref expansion up to *max_hops* hops.

    Initial top-k results are preserved at the front of the returned list.
    Expanded cross-reference nodes are appended after, deduplicated by qa_id.
    The expansion limit prevents runaway fetching when nodes have many cross_refs.
    """
    from harness.embed import get_node_by_id

    if max_hops == 0:
        return retrieve(index, query, mode=mode, k=k, embed_model=embed_model)

    initial = retrieve(index, query, mode=mode, k=k, embed_model=embed_model)
    seen_ids: set[str] = {qa_id for qa_id, _, _ in initial}
    expanded: list[RetrievalResult] = list(initial)

    frontier = list(initial)
    for _hop in range(max_hops):
        next_frontier: list[RetrievalResult] = []
        for qa_id, _score, meta in frontier:
            cross_refs: list[str] = meta.get("cross_refs") or []
            for ref_id in cross_refs:
                if ref_id in seen_ids:
                    continue
                ref_node = get_node_by_id(index, ref_id)
                if ref_node is None:
                    continue
                seen_ids.add(ref_id)
                ref_result = (ref_id, 0.0, dict(ref_node.metadata))
                expanded.append(ref_result)
                next_frontier.append(ref_result)
        if not next_frontier:
            break
        frontier = next_frontier

    log.debug(
        "recursive retrieve: initial=%d expanded=%d (hops=%d)",
        len(initial), len(expanded) - len(initial), max_hops,
    )
    return expanded


def _retrieve_hierarchical(
    index: VectorStoreIndex,
    query: str,
    *,
    k: int,
    hier_index: Any,
    top_doc_k: int,
    embed_model=None,
) -> list[RetrievalResult]:
    """
    Hierarchical retrieval: retrieve top-*top_doc_k* parent (page) nodes, then
    expand to all child Q&A nodes and re-rank by dense similarity.
    """
    from harness.embed import get_node_by_id

    # 1. Retrieve top parent nodes by dense similarity
    parent_retriever = hier_index.as_retriever(similarity_top_k=top_doc_k)
    parent_nodes = parent_retriever.retrieve(query)

    # 2. Collect all child qa_ids from matched parents
    child_qa_ids: list[str] = []
    seen_ids: set[str] = set()
    for pnws in parent_nodes:
        for cid in (pnws.node.metadata.get("child_qa_ids") or []):
            if cid not in seen_ids:
                seen_ids.add(cid)
                child_qa_ids.append(cid)

    if not child_qa_ids:
        log.debug("hierarchical: no children found, falling back to dense")
        return retrieve(index, query, mode="dense", k=k, embed_model=embed_model)

    # 3. Fetch child nodes from flat docstore (one pass — nodes reused in step 4)
    children_and_nodes: list[tuple[str, dict, Any]] = []  # (qa_id, meta, node)
    for cid in child_qa_ids:
        node = get_node_by_id(index, cid)
        if node is not None:
            children_and_nodes.append((cid, dict(node.metadata), node))

    children: list[RetrievalResult] = [(qa_id, 0.0, meta) for qa_id, meta, _ in children_and_nodes]

    # 4. Re-score children by dense similarity (embed query, compute dot product)
    try:
        from llama_index.core import Settings
        import numpy as np
        q_vec = Settings.embed_model.get_query_embedding(query)
        q_arr = np.array(q_vec, dtype=np.float32)
        q_norm = float(np.linalg.norm(q_arr))

        rescored: list[tuple[float, RetrievalResult]] = []
        for qa_id, meta, node in children_and_nodes:
            try:
                n_embed = node.embedding
                if n_embed:
                    n_arr = np.array(n_embed, dtype=np.float32)
                    sim = float(np.dot(q_arr, n_arr) / (q_norm * np.linalg.norm(n_arr) + 1e-9))
                else:
                    sim = 0.0
            except Exception:
                sim = 0.0
            rescored.append((sim, (qa_id, sim, meta)))

        rescored.sort(key=lambda x: x[0], reverse=True)
        results = [r for _, r in rescored[:k]]
        log.debug("hierarchical: %d parents → %d children → top %d", len(parent_nodes), len(children), len(results))
        return results

    except Exception as exc:
        log.warning("hierarchical re-ranking failed (%s); returning unscored children", exc)
        return children[:k]


# ---------------------------------------------------------------------------
# Unified strategy dispatcher
# ---------------------------------------------------------------------------

def retrieve_with_config(
    config: RetrievalConfig,
    index: VectorStoreIndex,
    query: str,
    *,
    hier_index: Any = None,
    embed_model=None,
) -> list[RetrievalResult]:
    """
    Retrieve Q&A nodes using the strategy specified in *config*.

    This is the single retrieval entry point used by run_eval.py, app.py, and
    harness/workflows/ — a single code path replacing former per-strategy ad-hoc retrieval.

    Args:
        config:      RetrievalConfig (built from YAML ``retrieval:`` section).
        index:       Flat VectorStoreIndex (always required).
        query:       Natural-language query string.
        hier_index:  Hierarchical parent VectorStoreIndex (required when
                     config.strategy == "hierarchical").
        embed_model: Override the embedding model (used in tests).

    Returns:
        Ordered list of (qa_id, score, metadata) — highest score first.
    """
    strategy = config.strategy

    if strategy == "flat":
        return retrieve(index, query, mode=config.mode, k=config.k, embed_model=embed_model)

    if strategy == "agentic":
        raise NotImplementedError(
            "'agentic' strategy is not handled by retrieve_with_config — "
            "use harness.chains.registry.get_chain() instead"
        )

    if strategy == "recursive":
        return _retrieve_recursive(
            index, query,
            mode=config.mode,
            k=config.k,
            max_hops=config.recursive.max_hops,
            embed_model=embed_model,
        )

    if strategy == "hierarchical":
        if hier_index is None:
            log.warning("hierarchical strategy requested but hier_index=None — falling back to flat")
            return retrieve(index, query, mode=config.mode, k=config.k, embed_model=embed_model)
        return _retrieve_hierarchical(
            index, query,
            k=config.k,
            hier_index=hier_index,
            top_doc_k=config.hierarchical.top_doc_k,
            embed_model=embed_model,
        )

    log.warning("Unknown retrieval strategy %r — falling back to flat", strategy)
    return retrieve(index, query, mode=config.mode, k=config.k, embed_model=embed_model)


def make_raw_retriever(
    config: RetrievalConfig,
    index: VectorStoreIndex,
    *,
    hier_index: Any = None,
    embed_model=None,
) -> Callable[[str], list[RetrievalResult]]:
    """
    Return a callable ``fn(query) -> list[RetrievalResult]`` configured for *config*.

    Used by run_eval.py which needs a plain function signature so ablation
    wrappers (A1/A2/A3) can be layered on top.
    """
    def _fn(query: str) -> list[RetrievalResult]:
        return retrieve_with_config(config, index, query, hier_index=hier_index, embed_model=embed_model)
    return _fn


# ---------------------------------------------------------------------------
# Ablation configuration + shared factory
# ---------------------------------------------------------------------------

@dataclass
class AblationConfig:
    """
    Ablation flags parsed from the ``ablation:`` YAML section.

    Kept separate from RetrievalConfig so retrieval semantics (strategy, mode, k)
    remain independent of the ablation stack (query expansion, topic filter, reranker).
    """
    query_expansion: dict = field(default_factory=dict)
    topic_filter: dict = field(default_factory=dict)
    reranker: str | None = None
    reranker_max_chunks: int = 5

    @classmethod
    def from_yaml(cls, abl_dict: dict) -> "AblationConfig":
        """Parse the ``ablation:`` YAML section into an AblationConfig."""
        return cls(
            query_expansion=abl_dict.get("query_expansion", {}),
            topic_filter=abl_dict.get("topic_filter", {}),
            reranker=abl_dict.get("reranker") or None,
            reranker_max_chunks=int(abl_dict.get("reranker_max_chunks", 5)),
        )

    @property
    def query_expansion_enabled(self) -> bool:
        return bool(self.query_expansion.get("enabled", False))

    @property
    def topic_filter_mode(self) -> str | None:
        if not self.topic_filter.get("enabled", False):
            return None
        return self.topic_filter.get("mode") or None


def build_retrieve_fn(
    ret_config: RetrievalConfig,
    abl_config: "AblationConfig",
    index: Any,
    hier_index: Any = None,
) -> Callable[[str], list[RetrievalResult]]:
    """
    Build a retrieval callable that applies the full ablation stack in order:
      A1 — optional query expansion
      base — retrieval per ret_config (strategy, mode, k)
      A2 — optional topic filter
      A3/A4 — optional LLM reranker

    The returned callable exposes a ``.ablation_config`` attribute pointing to
    *abl_config*, which workflows can read to populate ``config_attributes()``.

    Legacy FAISS path — runtime default is ``harness.retrieve_pg.build_retrieve_fn_pg``
    as of NARR-028 (2026-05-26). This factory is invoked only when
    ``EMA_RETRIEVER=faiss``. Both ``app.py`` and ``run_eval.py`` dispatch on
    that env var.
    """
    # Build query expander once (expensive: loads acronym dict)
    _expander = None
    if abl_config.query_expansion_enabled:
        try:
            from harness.ablations.a1_query_expansion import QueryExpander
            dict_path_str: str | None = abl_config.query_expansion.get("acronym_dict")
            if dict_path_str:
                from pathlib import Path as _Path
                _expander = QueryExpander(_Path(dict_path_str).expanduser())
            else:
                _expander = QueryExpander()
            log.info("A1 query expansion enabled (dict: %s)", _expander)
        except Exception as exc:
            log.warning("A1 query expansion unavailable: %s", exc)

    # Load hierarchical index if needed and not already provided
    _hier_index = hier_index
    if _hier_index is None and ret_config.strategy == "hierarchical":
        hier_dir = ret_config.hierarchical.summary_index_dir
        if hier_dir:
            try:
                from harness.embed_hierarchical import load_hierarchical_index
                _hier_index = load_hierarchical_index(Path(hier_dir).expanduser())
                log.info("Hierarchical index loaded from %s", hier_dir)
            except Exception as exc:
                log.warning("Could not load hierarchical index: %s — falling back to flat", exc)

    _base = make_raw_retriever(ret_config, index, hier_index=_hier_index)
    _topic_filter_mode = abl_config.topic_filter_mode
    _reranker_name = abl_config.reranker
    _reranker_max_chunks = abl_config.reranker_max_chunks

    def retrieve_fn(query: str) -> list[RetrievalResult]:
        # A1 — optional query expansion
        expanded = _expander.expand(query) if _expander else query
        if expanded != query:
            log.debug("A1 expanded: %r → %r", query, expanded)

        results = _base(expanded)

        # A2 — optional topic filter
        if _topic_filter_mode == "keyword":
            from harness.ablations.a2_topic_filter import filter_by_topic_keyword
            results = filter_by_topic_keyword(results, query)
        elif _topic_filter_mode == "concept":
            from harness.ablations.a2_topic_filter import make_concept_retriever
            retriever = make_concept_retriever(index, query, k=ret_config.k)
            try:
                results = _results_from_nodes(retriever.retrieve(expanded))
            except (ValueError, NotImplementedError) as exc:
                log.warning("A2 concept filter unavailable (%s) — falling back to base retrieval", exc)

        # A3/A4 — optional LLM reranker
        if _reranker_name == "sme":
            import harness.ablations.a3_reranker as _a3
            results = _a3.rerank(results, query, index, max_chunks=_reranker_max_chunks)
        elif _reranker_name == "generic":
            import harness.ablations.a4_reranker as _a4
            results = _a4.rerank(results, query, index, max_chunks=_reranker_max_chunks)

        return results

    retrieve_fn.ablation_config = abl_config  # type: ignore[attr-defined]
    return retrieve_fn
