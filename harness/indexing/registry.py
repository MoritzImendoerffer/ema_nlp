"""Index + retriever registries — the extension seam for the retrieval pipeline.

Adding a new index kind or retriever strategy is a registration + a profile
file; nothing in the workflows / chat UI / tracing changes. This mirrors the
existing ``harness/workflows/registry.py`` pattern.

    from harness.indexing import build_index, build_retriever, load_index_profile

    profile = load_index_profile()              # EMA_INDEX_PROFILE or default
    index   = build_index(profile)              # dispatch on index.kind
    retr    = build_retriever(profile, index)   # dispatch on retrieval.strategy

Builders self-register via the ``@register_index`` / ``@register_retriever``
decorators when their module is imported. ``harness.indexing.__init__`` imports
the concrete builder modules so registration happens on first use.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from harness.indexing.profiles import IndexProfile

# kind -> builder(profile, **kwargs) -> index object
INDEX_BUILDERS: dict[str, Callable[..., Any]] = {}
# strategy -> builder(profile, index, **kwargs) -> BaseRetriever
RETRIEVER_BUILDERS: dict[str, Callable[..., Any]] = {}


def register_index(kind: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        INDEX_BUILDERS[kind] = fn
        return fn

    return deco


def register_retriever(strategy: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        RETRIEVER_BUILDERS[strategy] = fn
        return fn

    return deco


def build_index(profile: IndexProfile, **kwargs: Any) -> Any:
    """Build (or load) the index for ``profile`` by dispatching on ``index.kind``."""
    kind = profile.index.kind
    builder = INDEX_BUILDERS.get(kind)
    if builder is None:
        raise NotImplementedError(
            f"No index builder registered for kind={kind!r}. "
            f"Registered: {sorted(INDEX_BUILDERS)}. "
            f"(The 'property_graph' builder lands in LIR-007.)"
        )
    return builder(profile, **kwargs)


def build_retriever(profile: IndexProfile, index: Any, **kwargs: Any) -> Any:
    """Build the retriever for ``profile`` by dispatching on ``retrieval.strategy``."""
    strategy = profile.retrieval.strategy
    builder = RETRIEVER_BUILDERS.get(strategy)
    if builder is None:
        raise NotImplementedError(
            f"No retriever builder registered for strategy={strategy!r}. "
            f"Registered: {sorted(RETRIEVER_BUILDERS)}. "
            f"(The 'hierarchical' retriever lands in LIR-008.)"
        )
    return builder(profile, index, **kwargs)


def list_index_kinds() -> list[str]:
    return sorted(INDEX_BUILDERS)


def list_retriever_strategies() -> list[str]:
    return sorted(RETRIEVER_BUILDERS)
