"""Config-driven retrieval pipeline (query expansion + rerank stages).

Native-first: stages are selected by name in config and composed around the
LlamaIndex retriever. See ``docs/TARGET_ARCHITECTURE.md`` §4.4.
"""

from harness.retrieval.config import RetrievalPipelineConfig, load_pipeline_config
from harness.retrieval.hubs import HubsConfig, HubSpec, HubWalk, load_hubs
from harness.retrieval.native_pg import (
    build_cypher_template_retriever,
    build_native_composed_retriever,
    build_vector_context_retriever,
)
from harness.retrieval.pipeline import run_retrieval
from harness.retrieval.postprocessors import (
    apply_postprocessors,
    build_postprocessors,
    get_postprocessor,
    list_postprocessors,
    register_postprocessor,
)
from harness.retrieval.routing import QueryRouter, RouteDecision, RoutingRule, load_router
from harness.retrieval.steering import (
    node_category,
    parse_categories,
    sort_by_category_priority,
    stratify_by_category,
)
from harness.retrieval.subgraphs import SubgraphPolicy, TopicSubgraphReader
from harness.retrieval.transforms import (
    get_transform,
    list_transforms,
    register_transform,
)

__all__ = [
    "HubSpec",
    "HubWalk",
    "HubsConfig",
    "QueryRouter",
    "RetrievalPipelineConfig",
    "RouteDecision",
    "RoutingRule",
    "SubgraphPolicy",
    "TopicSubgraphReader",
    "apply_postprocessors",
    "build_cypher_template_retriever",
    "build_native_composed_retriever",
    "build_postprocessors",
    "build_vector_context_retriever",
    "get_postprocessor",
    "get_transform",
    "list_postprocessors",
    "list_transforms",
    "load_hubs",
    "load_pipeline_config",
    "load_router",
    "node_category",
    "parse_categories",
    "register_postprocessor",
    "register_transform",
    "run_retrieval",
    "sort_by_category_priority",
    "stratify_by_category",
]
