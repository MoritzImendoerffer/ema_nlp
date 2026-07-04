"""Assemble an agent from config: tools (registry) + prompt + output schema.

``build_agent(llm=..., config=..., retriever=..., fetcher=...)`` is the single
entry point: it takes an ``AgentConfig`` (derived from a recipe by
``build_recipe``), resolves the toolset via the tool registry, loads the system
prompt, maps the output-schema name to a Pydantic class, and constructs the
``FunctionAgent``. Extra kwargs (``retriever=``, ``fetcher=``) are forwarded to
the tool builders.
"""

import logging
from typing import Any

from harness.agents.config import AgentConfig
from harness.agents.regulatory import build_regulatory_agent, load_agent_prompt
from harness.schemas import RegulatoryAnswer, Substance
from harness.tools import build_tools

log = logging.getLogger(__name__)

# Output-schema name -> Pydantic class. Extend via register_output_schema.
_OUTPUT_SCHEMAS: dict[str, type] = {
    "RegulatoryAnswer": RegulatoryAnswer,
    "Substance": Substance,
}


def register_output_schema(name: str, cls: type) -> None:
    """Register a Pydantic output schema under ``name`` (config-selectable)."""
    if name in _OUTPUT_SCHEMAS and _OUTPUT_SCHEMAS[name] is not cls:
        raise ValueError(f"Output schema {name!r} is already registered")
    _OUTPUT_SCHEMAS[name] = cls


def list_output_schemas() -> list[str]:
    """Sorted names of registered output schemas."""
    return sorted(_OUTPUT_SCHEMAS)


def get_output_schema(name: str) -> type:
    """Strict lookup: an unknown schema name is a hard config error, not a silent
    fallback — the trace stamp must never claim a schema that did not run (F2)."""
    try:
        return _OUTPUT_SCHEMAS[name]
    except KeyError:
        raise KeyError(
            f"Unknown output schema {name!r}. Registered: {list_output_schemas()}"
        ) from None


def build_agent(
    *,
    llm: Any,
    config: AgentConfig,
    **tool_kwargs: Any,
) -> Any:
    """Build a ``FunctionAgent`` from an explicit ``AgentConfig`` (one path, F6)."""
    cfg = config
    # Tool builders are NOT handed the agent LLM: a tool that needs its own model (e.g.
    # corrective_search's grader) builds the cheap, dedicated role from models.yaml itself
    # — keeping CRAG grading/rewriting off the expensive agent model. Tests inject a fake
    # grader by passing ``llm=`` directly to the tool builder.
    tools = build_tools(cfg.tools, **tool_kwargs)
    system_prompt = load_agent_prompt(cfg.system_prompt)
    output_cls = get_output_schema(cfg.output_schema)
    log.info(
        "building agent %r: tools=%s output_schema=%s", cfg.name, cfg.tools, cfg.output_schema
    )
    return build_regulatory_agent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        output_cls=output_cls,
        name=cfg.name,
    )
