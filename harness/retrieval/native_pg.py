"""Native PropertyGraph retriever composition (ontology / graph-native track).

Composes native LlamaIndex sub-retrievers over the existing ``PropertyGraphIndex``
(``index.property_graph_store``): ``VectorContextRetriever`` (vector seed + neighbour
expansion = small-to-big via ``path_depth``) and, for ontology mode,
``CypherTemplateRetriever``. Returned via ``index.as_retriever(sub_retrievers=[...])``.

The default runtime path uses the proven ``harness.indexing.build_retriever``
(``HierarchicalPGRetriever``); this module is the *native composition* alternative
for the ontology/graph-native track. Heavy classes are imported lazily and the
constructor signatures are verified against llama-index-core; behaviour is debugged
later on a live Neo4j graph.
"""

import logging
from typing import Any

log = logging.getLogger(__name__)


def build_vector_context_retriever(
    index: Any,
    *,
    embed_model: Any = None,
    similarity_top_k: int = 20,
    path_depth: int = 1,
    include_text: bool = True,
) -> Any:
    """Native vector-seed + neighbour-expansion retriever over the PG store."""
    from llama_index.core.indices.property_graph import VectorContextRetriever

    return VectorContextRetriever(
        graph_store=index.property_graph_store,
        embed_model=embed_model,
        similarity_top_k=similarity_top_k,
        path_depth=path_depth,
        include_text=include_text,
    )


def build_cypher_template_retriever(
    index: Any,
    *,
    output_cls: type,
    cypher_query: str,
    llm: Any = None,
) -> Any:
    """Native parametrized-Cypher retriever (preferred over free TextToCypher).

    ``output_cls`` is a Pydantic model whose fields are the template parameters the
    LLM fills; ``cypher_query`` is the parametrized Cypher for a typed ontology query.
    """
    from llama_index.core.indices.property_graph import CypherTemplateRetriever

    return CypherTemplateRetriever(
        graph_store=index.property_graph_store,
        output_cls=output_cls,
        cypher_query=cypher_query,
        llm=llm,
    )


def build_native_composed_retriever(
    index: Any,
    *,
    sub_retrievers: list | None = None,
    embed_model: Any = None,
    similarity_top_k: int = 20,
    path_depth: int = 1,
    include_text: bool = True,
) -> Any:
    """Compose sub-retrievers via ``index.as_retriever(sub_retrievers=[...])``.

    Defaults to a single ``VectorContextRetriever`` when ``sub_retrievers`` is None.
    """
    if sub_retrievers is None:
        sub_retrievers = [
            build_vector_context_retriever(
                index,
                embed_model=embed_model,
                similarity_top_k=similarity_top_k,
                path_depth=path_depth,
                include_text=include_text,
            )
        ]
    return index.as_retriever(sub_retrievers=sub_retrievers, include_text=include_text)
