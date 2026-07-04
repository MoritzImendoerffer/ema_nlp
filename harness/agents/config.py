"""Agent configuration — config-driven orchestration (aim 1 & 3).

An :class:`AgentConfig` declares an agent's system prompt, toolset, output schema
and retrieval profile. It is derived from a *recipe* by
:func:`harness.recipes.build_recipe` — recipes (``harness/configs/recipes/*.yaml``)
are the single config surface; there is no separate agent YAML (F6).
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Declarative description of an agent (derived from a recipe)."""

    name: str
    system_prompt: str = "agent_regulatory.md"
    tools: list[str] = field(default_factory=list)
    output_schema: str = "RegulatoryAnswer"
    retrieval_profile: str = "neo4j_hier"
