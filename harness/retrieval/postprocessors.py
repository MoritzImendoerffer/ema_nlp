"""Node-postprocessor (rerank) registry — config-selected ``BaseNodePostprocessor``s.

Reranking is a first-class, config-declared stage (the retrieval-quality
cornerstone). Builders for the real rerankers import their heavy dependencies
*lazily*, so this module imports cleanly and the registry/selection logic is
unit-testable without torch or a downloaded cross-encoder model.

See ``docs/TARGET_ARCHITECTURE.md`` §4.4.
"""

import logging
from collections.abc import Callable
from typing import Any

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import QueryBundle

log = logging.getLogger(__name__)

PostprocessorBuilder = Callable[..., BaseNodePostprocessor]

_REGISTRY: dict[str, PostprocessorBuilder] = {}

_NONE_NAMES = {"", "none", "off"}


def register_postprocessor(name: str) -> Callable[[PostprocessorBuilder], PostprocessorBuilder]:
    """Decorator: register a ``BaseNodePostprocessor`` builder under ``name``."""

    def _decorator(builder: PostprocessorBuilder) -> PostprocessorBuilder:
        if name in _REGISTRY:
            raise ValueError(f"Postprocessor {name!r} is already registered")
        _REGISTRY[name] = builder
        return builder

    return _decorator


def list_postprocessors() -> list[str]:
    """Sorted names of registered postprocessors."""
    return sorted(_REGISTRY)


def get_postprocessor(name: str, **kwargs: Any) -> BaseNodePostprocessor:
    """Instantiate the named postprocessor (forwards ``kwargs`` to its builder)."""
    if name not in _REGISTRY:
        available = ", ".join(list_postprocessors()) or "(none registered)"
        raise ValueError(f"Unknown postprocessor {name!r}. Available: {available}")
    return _REGISTRY[name](**kwargs)


def build_postprocessors(names: list[str], **kwargs: Any) -> list[BaseNodePostprocessor]:
    """Build an ordered list of postprocessors, skipping ``none``/empty entries."""
    out: list[BaseNodePostprocessor] = []
    for name in names:
        if name is None or str(name).lower() in _NONE_NAMES:
            continue
        out.append(get_postprocessor(name, **kwargs))
    return out


def apply_postprocessors(
    nodes: list,
    postprocessors: list[BaseNodePostprocessor],
    *,
    query: str,
) -> list:
    """Apply each postprocessor in order to ``nodes``."""
    qb = QueryBundle(query_str=query)
    for postprocessor in postprocessors:
        nodes = postprocessor.postprocess_nodes(nodes, query_bundle=qb)
    return nodes


# --- built-in builders (heavy deps imported lazily; not exercised by unit tests) ---


@register_postprocessor("cross_encoder")
def build_cross_encoder(
    *, model: str = "BAAI/bge-reranker-large", top_n: int = 8, **_: Any
) -> BaseNodePostprocessor:
    """Local cross-encoder reranker (fast, reproducible). Requires the sbert extra."""
    from llama_index.core.postprocessor import SentenceTransformerRerank

    return SentenceTransformerRerank(model=model, top_n=top_n)


@register_postprocessor("llm_sme")
def build_llm_sme(*, llm: Any = None, top_n: int = 8, **_: Any) -> BaseNodePostprocessor:
    """LLM reranker (optionally with the SME relevance rubric as its prompt)."""
    from llama_index.core.postprocessor import LLMRerank

    return LLMRerank(llm=llm, top_n=top_n)
