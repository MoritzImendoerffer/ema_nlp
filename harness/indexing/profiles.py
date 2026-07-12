"""Index profile schema + loader for the LlamaIndex-first retrieval pipeline.

A *profile* is a YAML file under ``harness/configs/index/<name>.yaml`` that
describes how to build an index and which retriever to attach. The active
profile is selected by the ``EMA_INDEX_PROFILE`` env var (default
``neo4j_hier``), so swapping retrieval setups is an env change, not a code edit.

Neo4j connection details are deliberately *not* in the profile — they are
credentials and come from ``NEO4J_URI`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD`` at
build time (see ``harness.indexing.neo4j_store``, added in LIR-007).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE = "neo4j_hier"
PROFILE_ENV = "EMA_INDEX_PROFILE"
PROFILE_DIR = Path(__file__).resolve().parent.parent / "configs" / "index"


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


@dataclass
class ScopeConfig:
    """Subset selector applied during ingestion (R3 — subset-first)."""

    committee: list[str] = field(default_factory=list)
    topic_prefix: str | None = None
    limit: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ScopeConfig:
        d = d or {}
        topic = d.get("topic_prefix") or None
        raw_limit = d.get("limit")
        limit = int(raw_limit) if raw_limit not in (None, "", 0, "0") else None
        return cls(committee=_as_str_list(d.get("committee")), topic_prefix=topic, limit=limit)


@dataclass
class ChunkingConfig:
    parser: str = "hierarchical"
    chunk_sizes: list[int] = field(default_factory=lambda: [2048, 512, 128])
    min_chunk_chars: int = 80

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ChunkingConfig:
        d = d or {}
        sizes = d.get("chunk_sizes") or [2048, 512, 128]
        chunk_sizes = [int(s) for s in sizes]
        if any(s <= 0 for s in chunk_sizes):
            raise ValueError(f"chunk_sizes must be positive, got {chunk_sizes}")
        return cls(
            parser=str(d.get("parser", "hierarchical")),
            chunk_sizes=chunk_sizes,
            min_chunk_chars=int(d.get("min_chunk_chars", 80)),
        )


@dataclass
class StoreConfig:
    """Backing store selector. Connection comes from env, not the profile."""

    graph: str = "neo4j"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> StoreConfig:
        d = d or {}
        return cls(graph=str(d.get("graph", "neo4j")))


@dataclass
class IndexConfig:
    kind: str = "property_graph"
    source: str = "mongo_parsed_documents"
    embed_model: str = "BAAI/bge-large-en-v1.5"
    store: StoreConfig = field(default_factory=StoreConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    scope: ScopeConfig = field(default_factory=ScopeConfig)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> IndexConfig:
        d = d or {}
        return cls(
            kind=str(d.get("kind", "property_graph")),
            source=str(d.get("source", "mongo_parsed_documents")),
            embed_model=str(d.get("embed_model", "BAAI/bge-large-en-v1.5")),
            store=StoreConfig.from_dict(d.get("store")),
            chunking=ChunkingConfig.from_dict(d.get("chunking")),
            scope=ScopeConfig.from_dict(d.get("scope")),
        )


# Valid DOM-context values for LINKS_TO edges (mirrors harness.indexing.links.LINK_CONTEXTS;
# duplicated here as a literal to avoid a profiles->links->chunking->profiles import cycle).
VALID_LINK_CONTEXTS = ("file_component", "card_or_listing", "inline", "other")


@dataclass
class GraphRetrievalConfig:
    max_hops: int = 1
    edge_types: list[str] = field(default_factory=lambda: ["links_to"])
    # ── link-extraction upgrade: filter LINKS_TO expansion by DOM context ─────
    # Default keeps the content-bearing contexts and drops ``other`` (standalone
    # anchors). ``document_types`` empty = no edge doc-type filter.
    link_contexts: list[str] = field(
        default_factory=lambda: ["file_component", "card_or_listing", "inline"]
    )
    document_types: list[str] = field(default_factory=list)
    # ── link-graph expansion (steering Option B) ──────────────────────────────
    # When ``expand`` is on, ``HierarchicalPGRetriever`` follows the configured
    # edges from the vector-hit documents (up to ``max_hops``) and appends the
    # best-matching chunk of up to ``max_expand`` linked documents — restricted
    # to ``expand_categories`` when set ([] = any category). Additive: expansion
    # never displaces a vector hit. Requires backfilled ``:Document.category``
    # for the category restriction (scripts/backfill_doc_categories.py).
    expand: bool = False
    expand_categories: list[str] = field(default_factory=list)
    max_expand: int = 3

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> GraphRetrievalConfig:
        d = d or {}
        max_hops = int(d.get("max_hops", 1))
        if max_hops < 0:
            raise ValueError("graph.max_hops must be >= 0")
        link_contexts = _as_str_list(d.get("link_contexts")) or [
            "file_component", "card_or_listing", "inline"
        ]
        unknown = [c for c in link_contexts if c not in VALID_LINK_CONTEXTS]
        if unknown:
            raise ValueError(
                f"graph.link_contexts has unknown value(s) {unknown}; "
                f"valid: {list(VALID_LINK_CONTEXTS)}"
            )
        expand = bool(d.get("expand", False))
        expand_categories = _as_str_list(d.get("expand_categories"))
        if expand_categories:
            from harness.retrieval.doc_categories import CATEGORIES

            bad = [c for c in expand_categories if c not in CATEGORIES]
            if bad:
                raise ValueError(
                    f"graph.expand_categories has unknown categor(ies) {bad}; "
                    f"valid: {list(CATEGORIES)}"
                )
        max_expand = int(d.get("max_expand", 3))
        if max_expand < 1:
            raise ValueError("graph.max_expand must be >= 1")
        if expand and max_hops < 1:
            raise ValueError("graph.expand requires max_hops >= 1")
        return cls(
            max_hops=max_hops,
            edge_types=_as_str_list(d.get("edge_types")) or ["links_to"],
            link_contexts=link_contexts,
            document_types=_as_str_list(d.get("document_types")),
            expand=expand,
            expand_categories=expand_categories,
            max_expand=max_expand,
        )


@dataclass
class RetrievalConfig:
    strategy: str = "hierarchical"
    k: int = 10
    merge: bool = True
    # ── source-category steering (Option A) ───────────────────────────────────
    # ``oversample`` sizes the candidate pool (k * oversample vector hits) used
    # whenever a category filter or quota is active — filtering/stratifying a
    # plain top-k would just shrink it. ``category_quota`` maps category ->
    # guaranteed slots within the final k (e.g. {scientific_guideline: 2});
    # empty = no stratification. Categories come from
    # harness.retrieval.doc_categories.CATEGORIES — nothing is hardcoded here.
    oversample: int = 4
    category_quota: dict[str, int] = field(default_factory=dict)
    graph: GraphRetrievalConfig = field(default_factory=GraphRetrievalConfig)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> RetrievalConfig:
        d = d or {}
        k = int(d.get("k", 10))
        if k <= 0:
            raise ValueError("retrieval.k must be > 0")
        oversample = int(d.get("oversample", 4))
        if oversample < 1:
            raise ValueError("retrieval.oversample must be >= 1")
        raw_quota = d.get("category_quota") or {}
        category_quota = {str(c): int(n) for c, n in raw_quota.items()}
        if category_quota:
            from harness.retrieval.steering import validate_quota

            validate_quota(category_quota, k=k)
        return cls(
            strategy=str(d.get("strategy", "hierarchical")),
            k=k,
            merge=bool(d.get("merge", True)),
            oversample=oversample,
            category_quota=category_quota,
            graph=GraphRetrievalConfig.from_dict(d.get("graph")),
        )


@dataclass
class IndexProfile:
    name: str
    index: IndexConfig
    retrieval: RetrievalConfig

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> IndexProfile:
        return cls(
            name=name,
            index=IndexConfig.from_dict(d.get("index")),
            retrieval=RetrievalConfig.from_dict(d.get("retrieval")),
        )


def resolve_profile_name(name: str | None = None) -> str:
    """Profile name: explicit arg > ``EMA_INDEX_PROFILE`` env > default."""
    return name or os.getenv(PROFILE_ENV) or DEFAULT_PROFILE


def load_index_profile(name: str | None = None, *, profile_dir: Path | None = None) -> IndexProfile:
    """Load and parse the named profile (or the env-selected / default one).

    Profiles follow the same search path as recipes/prompts (F9): an explicit
    ``profile_dir`` (tests) wins, else ``$EMA_CONFIG_DIR/index/`` shadows the
    built-in ``harness/configs/index/``.
    """
    from harness.config_paths import find_config, list_config_stems

    name = resolve_profile_name(name)
    if profile_dir is not None:
        path = profile_dir / f"{name}.yaml"
        if not path.exists():
            available = sorted(p.stem for p in profile_dir.glob("*.yaml")) if profile_dir.exists() else []
            raise FileNotFoundError(
                f"index profile {name!r} not found at {path}. Available: {available}"
            )
    else:
        path = find_config("index", f"{name}.yaml")
        if path is None:
            raise FileNotFoundError(
                f"index profile {name!r} not found (searched $EMA_CONFIG_DIR/index and the "
                f"built-in index/). Available: {list_config_stems('index')}"
            )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return IndexProfile.from_dict(name, data)
