"""Tool registry + built-in FunctionTools for the agentic pipeline (aim 3).

Importing this package registers the built-in tools (``ema_search``,
``resolve_substance``) as a side effect. See ``docs/TARGET_ARCHITECTURE.md`` §4.3.
"""

from harness.tools import search as _search  # noqa: F401  (registers ema_search)
from harness.tools import substance as _substance  # noqa: F401  (registers resolve_substance)
from harness.tools.registry import build_tools, get_tool, list_tools, register_tool

__all__ = [
    "build_tools",
    "get_tool",
    "list_tools",
    "register_tool",
]
