"""Tool registry + built-in FunctionTools for the agentic pipeline (aim 3).

Importing this package registers the built-in tools (``ema_search``,
``corrective_search``, ``resolve_substance``, ``topic_context``) as a side
effect. See ``docs/TARGET_ARCHITECTURE.md`` §4.3 and ``docs/RAG_TECHNIQUES.md``.
"""

from harness.tools import (
    corrective_search as _corrective,  # noqa: F401  (registers corrective_search)
)
from harness.tools import search as _search  # noqa: F401  (registers ema_search)
from harness.tools import substance as _substance  # noqa: F401  (registers resolve_substance)
from harness.tools import topic_context as _topic  # noqa: F401  (registers topic_context)
from harness.tools.registry import build_tools, get_tool, list_tools, register_tool

__all__ = [
    "build_tools",
    "get_tool",
    "list_tools",
    "register_tool",
]
