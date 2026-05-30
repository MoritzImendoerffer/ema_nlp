"""LlamaIndex-first retrieval pipeline: config-driven index + retriever factories.

Public surface:
    load_index_profile(name=None)        — parse the env-selected / named profile
    build_index(profile, **kw)           — dispatch on index.kind
    build_retriever(profile, index, **kw)— dispatch on retrieval.strategy
    register_index / register_retriever  — extension decorators

Concrete builders are imported here so their @register decorators run. As they
land (LIR-006/007/008) add their imports to the "builders" block below.
"""

from __future__ import annotations

from harness.indexing.profiles import (
    IndexProfile,
    load_index_profile,
    resolve_profile_name,
)
from harness.indexing.registry import (
    build_index,
    build_retriever,
    list_index_kinds,
    list_retriever_strategies,
    register_index,
    register_retriever,
)

# ── builders (self-register on import) ──────────────────────────────────────
# LIR-007: from harness.indexing import property_graph_index  # noqa: F401
# LIR-008: from harness.indexing import hierarchical_retriever  # noqa: F401

__all__ = [
    "IndexProfile",
    "load_index_profile",
    "resolve_profile_name",
    "build_index",
    "build_retriever",
    "register_index",
    "register_retriever",
    "list_index_kinds",
    "list_retriever_strategies",
]
