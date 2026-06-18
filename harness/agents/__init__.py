"""Agentic orchestration layer (native LlamaIndex FunctionAgent).

Replaces the hand-rolled workflow orchestration with config-driven agents.
See ``docs/TARGET_ARCHITECTURE.md`` §4.1.
"""

from harness.agents.config import AgentConfig, load_agent_config
from harness.agents.registry import build_agent
from harness.agents.regulatory import build_regulatory_agent, load_agent_prompt
from harness.agents.runner import arun_agent, coerce_answer, run_agent
from harness.agents.session import AgentSession, assemble_agent, build_session

__all__ = [
    "AgentConfig",
    "AgentSession",
    "arun_agent",
    "assemble_agent",
    "build_agent",
    "build_regulatory_agent",
    "build_session",
    "coerce_answer",
    "load_agent_config",
    "load_agent_prompt",
    "run_agent",
]
