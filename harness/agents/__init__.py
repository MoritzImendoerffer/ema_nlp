"""Agentic orchestration layer (native LlamaIndex FunctionAgent).

Replaces the hand-rolled workflow orchestration with config-driven agents.
See ``docs/TARGET_ARCHITECTURE.md`` §4.1.
"""

from harness.agents.config import AgentConfig, load_agent_config
from harness.agents.registry import build_agent
from harness.agents.regulatory import build_regulatory_agent, load_agent_prompt

__all__ = [
    "AgentConfig",
    "build_agent",
    "build_regulatory_agent",
    "load_agent_config",
    "load_agent_prompt",
]
