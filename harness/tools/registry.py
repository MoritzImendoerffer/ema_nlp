"""Tool registry — ``FunctionTool`` builders selectable by name (config-driven).

Mirrors the workflow/index registries: an agent declares its toolset by name in
config (``harness/configs/agent/<name>.yaml``) and ``build_tools`` resolves the
names to LlamaIndex ``FunctionTool`` instances.

Builders accept ``**kwargs`` (e.g. ``retriever=``, ``fetcher=``) and ignore the
ones they don't need, so a single ``build_tools(names, retriever=..., fetcher=...)``
call can construct a heterogeneous toolset.
"""

import logging
from collections.abc import Callable
from typing import Any

from llama_index.core.tools import FunctionTool

log = logging.getLogger(__name__)

ToolBuilder = Callable[..., FunctionTool]

_TOOL_REGISTRY: dict[str, ToolBuilder] = {}


def register_tool(name: str) -> Callable[[ToolBuilder], ToolBuilder]:
    """Decorator: register a ``FunctionTool`` builder under ``name``."""

    def _decorator(builder: ToolBuilder) -> ToolBuilder:
        if name in _TOOL_REGISTRY:
            raise ValueError(f"Tool {name!r} is already registered")
        _TOOL_REGISTRY[name] = builder
        return builder

    return _decorator


def list_tools() -> list[str]:
    """Return the sorted names of all registered tools."""
    return sorted(_TOOL_REGISTRY)


def get_tool(name: str, **kwargs: Any) -> FunctionTool:
    """Instantiate the named tool, forwarding ``kwargs`` to its builder."""
    if name not in _TOOL_REGISTRY:
        available = ", ".join(list_tools()) or "(none registered)"
        raise ValueError(f"Unknown tool {name!r}. Available: {available}")
    return _TOOL_REGISTRY[name](**kwargs)


def build_tools(names: list[str], **kwargs: Any) -> list[FunctionTool]:
    """Build a list of tools by name (shared ``kwargs`` forwarded to each builder)."""
    return [get_tool(n, **kwargs) for n in names]
