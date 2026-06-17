"""Agent configuration loading — config-driven orchestration (aim 1 & 3).

An agent is fully described by a YAML file under ``harness/configs/agent/``:
its model role, system prompt, toolset, output schema, retrieval profile, and
few-shot policy. Nothing about *which* tools or *which* schema is hardcoded.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "configs" / "agent"


@dataclass
class AgentConfig:
    """Declarative description of an agent (loaded from YAML)."""

    name: str
    model_role: str = "agent"
    system_prompt: str = "agent_regulatory.md"
    tools: list[str] = field(default_factory=list)
    output_schema: str = "RegulatoryAnswer"
    retrieval_profile: str = "neo4j_hier"
    fewshot: dict[str, Any] = field(default_factory=dict)


def load_agent_config(name: str, *, config_dir: Path | None = None) -> AgentConfig:
    """Load ``harness/configs/agent/<name>.yaml`` into an ``AgentConfig``."""
    directory = config_dir or CONFIG_DIR
    path = directory / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Agent config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    agent = raw.get("agent", raw)
    return AgentConfig(
        name=name,
        model_role=agent.get("model_role", "agent"),
        system_prompt=agent.get("system_prompt", "agent_regulatory.md"),
        tools=list(agent.get("tools", [])),
        output_schema=agent.get("output_schema", "RegulatoryAnswer"),
        retrieval_profile=agent.get("retrieval_profile", "neo4j_hier"),
        fewshot=dict(agent.get("fewshot", {})),
    )
