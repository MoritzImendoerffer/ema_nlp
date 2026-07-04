"""Agentic orchestration layer (native LlamaIndex FunctionAgent).

Replaces the hand-rolled workflow orchestration with config-driven agents.
See ``docs/TARGET_ARCHITECTURE.md`` §4.1.
"""

from harness.agents.config import AgentConfig
from harness.agents.registry import (
    build_agent,
    get_output_schema,
    list_output_schemas,
    register_output_schema,
)
from harness.agents.regulatory import build_regulatory_agent, load_agent_prompt
from harness.agents.runner import arun_agent, coerce_answer, run_agent
from harness.agents.session import AgentSession, assemble_agent

__all__ = [
    "AgentConfig",
    "AgentSession",
    "arun_agent",
    "assemble_agent",
    "build_agent",
    "build_regulatory_agent",
    "coerce_answer",
    "get_output_schema",
    "list_output_schemas",
    "load_agent_prompt",
    "register_output_schema",
    "run_agent",
]
