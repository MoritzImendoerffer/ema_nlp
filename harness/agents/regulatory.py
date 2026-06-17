"""Build the EMA regulatory agent as a native LlamaIndex ``FunctionAgent`` (aim 3).

The agent's structured final answer is enforced natively via ``output_cls``
(``RegulatoryAnswer``) — that is, structured output (aim 2) and traceable
citations (aim 4) come from the framework, not a post-hoc parse.
"""

import logging
from pathlib import Path
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent

from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_agent_prompt(name: str) -> str:
    """Read an agent system prompt from ``harness/prompts/``."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Agent prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def build_regulatory_agent(
    *,
    llm: Any,
    tools: list,
    system_prompt: str,
    output_cls: type = RegulatoryAnswer,
    name: str = "regulatory",
    description: str = "Answers EMA human-regulatory questions with cited evidence.",
) -> FunctionAgent:
    """Construct a ``FunctionAgent`` with the given tools, prompt, and output schema."""
    return FunctionAgent(
        name=name,
        description=description,
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        output_cls=output_cls,
    )
