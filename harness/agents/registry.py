"""Assemble an agent from config: tools (registry) + prompt + output schema.

``build_agent("regulatory", llm=..., retriever=..., fetcher=...)`` is the single
entry point: it reads the YAML config, resolves the toolset via the tool registry,
loads the system prompt, maps the output-schema name to a Pydantic class, and
constructs the ``FunctionAgent``. Extra kwargs (``retriever=``, ``fetcher=``) are
forwarded to the tool builders.
"""

import logging
from typing import Any

from harness.agents.config import AgentConfig, load_agent_config
from harness.agents.regulatory import build_regulatory_agent, load_agent_prompt
from harness.schemas import RegulatoryAnswer
from harness.tools import build_tools

log = logging.getLogger(__name__)

# Output-schema name -> Pydantic class. Extend as new report formats are added.
_OUTPUT_SCHEMAS: dict[str, type] = {
    "RegulatoryAnswer": RegulatoryAnswer,
}


def build_agent(
    name: str,
    *,
    llm: Any,
    config: AgentConfig | None = None,
    **tool_kwargs: Any,
) -> Any:
    """Build a configured ``FunctionAgent`` by name (or from a provided config)."""
    cfg = config or load_agent_config(name)
    tools = build_tools(cfg.tools, **tool_kwargs)
    system_prompt = load_agent_prompt(cfg.system_prompt)
    output_cls = _OUTPUT_SCHEMAS.get(cfg.output_schema, RegulatoryAnswer)
    log.info(
        "building agent %r: tools=%s output_schema=%s", name, cfg.tools, cfg.output_schema
    )
    return build_regulatory_agent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        output_cls=output_cls,
        name=name,
    )
