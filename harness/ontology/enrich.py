"""Enrich the Neo4j graph with the typed semantic ontology layer (Layer 2).

Maps an :class:`OntologySchema` to a LlamaIndex ``SchemaLLMPathExtractor`` and runs
it over a scoped set of documents, writing typed entities + relations into the
existing ``PropertyGraphIndex``. The schema→extractor mapping and the dry-run plan
are pure (and tested); the extraction itself is LLM- and Neo4j-backed, so it is
lazy + runtime (debugged on the GPU host).

CLI::

    python -m harness.ontology.enrich --schema ema --scope nitrosamines --dry-run
    python -m harness.ontology.enrich --schema ema --scope nitrosamines
    python -m harness.ontology.enrich --schema ema --scope all
"""

import argparse
import logging
from typing import Any

from harness.ontology.schema import OntologySchema, load_ontology_schema

log = logging.getLogger(__name__)

# Keyword scopes for incremental enrichment (start small, then "all").
_SCOPE_KEYWORDS: dict[str, list[str]] = {
    "nitrosamines": ["nitrosamine", "ndma", "ndea", "acceptable intake"],
}


def schema_extractor_kwargs(schema: OntologySchema) -> dict[str, Any]:
    """Map an OntologySchema to ``SchemaLLMPathExtractor`` kwargs (pure)."""
    return {
        "possible_entities": list(schema.entities),
        "possible_relations": list(schema.relations),
        "kg_validation_schema": [list(t) for t in schema.as_triples()],
        "strict": True,
    }


def enrichment_plan(schema_name: str = "ema", scope: str = "all") -> dict[str, Any]:
    """Pure description of what an enrichment run would do (used by --dry-run)."""
    schema = load_ontology_schema(schema_name)
    return {
        "schema": schema_name,
        "scope": scope,
        "scope_keywords": _SCOPE_KEYWORDS.get(scope, []),
        "entities": len(schema.entities),
        "relations": len(schema.relations),
        "validation_triples": len(schema.as_triples()),
        "extractor_kwargs": schema_extractor_kwargs(schema),
    }


def build_schema_extractor(
    schema: OntologySchema,
    llm: Any,
    *,
    max_triplets_per_chunk: int = 8,
    num_workers: int = 4,
) -> Any:
    """Construct a ``SchemaLLMPathExtractor`` from the schema (lazy import)."""
    from llama_index.core.indices.property_graph import SchemaLLMPathExtractor

    return SchemaLLMPathExtractor(
        llm=llm,
        max_triplets_per_chunk=max_triplets_per_chunk,
        num_workers=num_workers,
        **schema_extractor_kwargs(schema),
    )


def _scoped_chunk_nodes(scope: str, *, profile_name: str | None, limit: int | None) -> list:
    """Build TextNodes for the scope from the existing ingest layer (runtime).

    Reuses ``harness.indexing.ingest`` so the same chunking/IR feeds extraction.
    A keyword scope keeps only docs whose text/title matches (incremental enrich);
    ``all`` keeps everything (subject to ``limit``).
    """
    from pymongo import MongoClient

    from config import MONGO_URI
    from harness.indexing import load_index_profile
    from harness.indexing.ingest import build_ingested_doc, iter_source_rows, mongo_html_lookup

    profile = load_index_profile(profile_name)
    keywords = [k.lower() for k in _SCOPE_KEYWORDS.get(scope, [])]
    client = MongoClient(MONGO_URI)
    nodes: list = []
    try:
        lookup = mongo_html_lookup(client)
        for row in iter_source_rows(profile.index.scope, client=client):
            if not row.get("url"):
                continue
            doc = build_ingested_doc(row, chunking=profile.index.chunking, html_lookup=lookup)
            if keywords:
                hay = f"{doc.title} {' '.join(getattr(c, 'text', '') for c in doc.chunk_nodes)}".lower()
                if not any(k in hay for k in keywords):
                    continue
            nodes.extend(doc.chunk_nodes)
            if limit and len({c.metadata.get('doc_id') for c in nodes}) >= limit:
                break
    finally:
        client.close()
    return nodes


def enrich_ontology(
    scope: str = "all",
    *,
    schema_name: str = "ema",
    model_role: str = "grader",
    profile_name: str | None = None,
    limit: int | None = None,
    max_triplets_per_chunk: int = 8,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run schema-constrained extraction over ``scope`` and upsert typed triples.

    ``dry_run=True`` returns the plan without touching Neo4j/the LLM. The runtime
    path inserts scoped chunks through a ``SchemaLLMPathExtractor`` attached to the
    existing PropertyGraphIndex (idempotent MERGE semantics in the Neo4j store).
    """
    plan = enrichment_plan(schema_name, scope)
    if dry_run:
        log.info("ontology enrichment plan: %s", {k: plan[k] for k in plan if k != "extractor_kwargs"})
        return plan

    # ── runtime (lazy: Neo4j + LLM + embeddings) ──────────────────────────────
    from llama_index.core import PropertyGraphIndex

    from harness.indexing.property_graph import _embed_model, neo4j_store_from_env
    from harness.llms import get_llm

    schema = load_ontology_schema(schema_name)
    llm = get_llm(model_role)
    extractor = build_schema_extractor(schema, llm, max_triplets_per_chunk=max_triplets_per_chunk)
    store = neo4j_store_from_env()
    # kg_extractors run on insert; embed_kg_nodes=False keeps the chunk vector index intact.
    index = PropertyGraphIndex.from_existing(
        property_graph_store=store,
        embed_model=_embed_model(),
        llm=llm,
        kg_extractors=[extractor],
        embed_kg_nodes=False,
    )
    nodes = _scoped_chunk_nodes(scope, profile_name=profile_name, limit=limit)
    log.info("enrich: inserting %d scoped chunks through SchemaLLMPathExtractor", len(nodes))
    index.insert_nodes(nodes)
    return {**plan, "inserted_nodes": len(nodes)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Enrich the graph with the typed ontology layer")
    parser.add_argument("--schema", default="ema")
    parser.add_argument("--scope", default="all", help="all | nitrosamines | <keyword-scope>")
    parser.add_argument("--model-role", default="grader")
    parser.add_argument("--profile", default=None, help="index profile name (EMA_INDEX_PROFILE)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = enrich_ontology(
        args.scope,
        schema_name=args.schema,
        model_role=args.model_role,
        profile_name=args.profile,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print({k: result[k] for k in result if k != "extractor_kwargs"})


if __name__ == "__main__":
    main()
