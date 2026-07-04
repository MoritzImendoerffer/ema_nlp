"""Query-transform registry — config-selected query expansion / rewriting.

A transform maps a query string to one or more query variants (multi-query). The
"specialized query-expansion agent" plugs into this same seam as a future
``agent`` impl; today it ships:

  - ``none``        identity (testable)
  - ``acronym``     deterministic acronym expansion from an injected mapping
                    (testable; directly attacks "AI = Acceptable Intake")
  - ``llm_rewrite`` LLM paraphrase expansion (runtime; requires an ``llm``)

See ``docs/TARGET_ARCHITECTURE.md`` §4.4.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# A transform takes a query and returns 1+ query variants (the original first).
QueryTransform = Callable[[str], list[str]]
TransformBuilder = Callable[..., QueryTransform]

_REGISTRY: dict[str, TransformBuilder] = {}


def register_transform(name: str) -> Callable[[TransformBuilder], TransformBuilder]:
    """Decorator: register a query-transform builder under ``name``."""

    def _decorator(builder: TransformBuilder) -> TransformBuilder:
        if name in _REGISTRY:
            raise ValueError(f"Query transform {name!r} is already registered")
        _REGISTRY[name] = builder
        return builder

    return _decorator


def list_transforms() -> list[str]:
    """Sorted names of registered query transforms."""
    return sorted(_REGISTRY)


def get_transform(name: str, **kwargs: Any) -> QueryTransform:
    """Instantiate the named query transform (forwards ``kwargs`` to its builder)."""
    if name not in _REGISTRY:
        available = ", ".join(list_transforms()) or "(none registered)"
        raise ValueError(f"Unknown query transform {name!r}. Available: {available}")
    return _REGISTRY[name](**kwargs)


@register_transform("none")
def build_identity(**_: Any) -> QueryTransform:
    """Identity transform — returns the query unchanged."""

    def _transform(query: str) -> list[str]:
        return [query]

    return _transform


@register_transform("acronym")
def build_acronym(*, acronyms: dict[str, str] | None = None, **_: Any) -> QueryTransform:
    """Expand known acronyms into an extra query variant.

    With an explicit ``acronyms`` mapping, does plain word-boundary substitution
    (deterministic, used by tests). With ``acronyms=None`` (the config-driven
    default), uses the context-aware :class:`~harness.retrieval.acronyms.QueryExpander`
    over the EMA acronym dictionary (``configs/retrieval/acronyms.yaml``) — this
    is the path that disambiguates "AI = Acceptable Intake".
    """
    if acronyms is None:
        from harness.retrieval.acronyms import QueryExpander

        expander = QueryExpander()  # raises if the dictionary is missing (no silent no-op)

        def _transform_dict(query: str) -> list[str]:
            expanded = expander.expand(query)
            return [query, expanded] if expanded != query else [query]

        return _transform_dict

    mapping = dict(acronyms)

    def _transform(query: str) -> list[str]:
        expanded = query
        for acronym, full in mapping.items():
            expanded = re.sub(rf"\b{re.escape(acronym)}\b", full, expanded)
        return [query, expanded] if expanded != query else [query]

    return _transform


@register_transform("llm_rewrite")
def build_llm_rewrite(*, llm: Any = None, n: int = 3, **_: Any) -> QueryTransform:
    """LLM paraphrase expansion (runtime). Requires an ``llm``; not unit-tested."""
    if llm is None:
        raise ValueError("llm_rewrite query transform requires an `llm`")

    def _transform(query: str) -> list[str]:
        prompt = (
            f"Rewrite the search query below into {n} diverse paraphrases that would "
            f"retrieve the same regulatory information. One per line, no numbering.\n\n"
            f"Query: {query}"
        )
        text = str(llm.complete(prompt))
        variants = [ln.strip("-• ").strip() for ln in text.splitlines() if ln.strip()]
        return [query, *variants[:n]]

    return _transform
