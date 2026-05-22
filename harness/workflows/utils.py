"""
Shared utilities for LlamaIndex workflow steps.

Provides:
  - Doc           lightweight document container (compatible with app.py's .metadata/.page_content API)
  - load_system_prompt()   read prompt from harness/prompts/
  - results_to_docs()      convert RetrievalResult tuples to Doc objects
  - format_docs()          render Doc list as a formatted context string
  - extract_answer()       strip CoT reasoning block from raw LLM output
  - build_rag_messages()   construct system+user ChatMessage list for RAG prompts
  - WorkflowRunner         thin sync/async wrapper for LlamaIndex Workflow instances
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_PROMPT_FILES: dict[str, str] = {
    "zero_shot": "system_zero_shot.md",
    "few_shot": "system_few_shot_sme.md",
    "cot_self": "system_cot_self.md",
}


# ---------------------------------------------------------------------------
# Doc: lightweight LangChain-compatible document container
# ---------------------------------------------------------------------------

@dataclass
class Doc:
    """Minimal document container with .page_content and .metadata attributes.

    Matches the interface used by app.py when iterating retrieved documents,
    so the Chainlit UI works without changes.
    """
    page_content: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_system_prompt(strategy: str) -> str:
    fname = _PROMPT_FILES.get(strategy)
    if fname is None:
        raise ValueError(
            f"Unknown strategy {strategy!r}. Choose from: {list(_PROMPT_FILES)}"
        )
    return (PROMPTS_DIR / fname).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Retrieval result helpers
# ---------------------------------------------------------------------------

def results_to_docs(results: list, index: Any) -> list[Doc]:
    """Convert (qa_id, score, metadata) triples to Doc objects."""
    from harness.embed import get_node_by_id

    docs: list[Doc] = []
    for qa_id, score, meta in results:
        node = get_node_by_id(index, qa_id)
        page_content = node.text if node is not None else f"[qa_id: {qa_id}]"
        docs.append(Doc(
            page_content=page_content,
            metadata={**meta, "qa_id": qa_id, "score": score},
        ))
    return docs


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_docs(docs: list[Doc]) -> str:
    if not docs:
        return "No relevant documents retrieved."
    lines: list[str] = ["## Retrieved Q&A documents", ""]
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        qa_id = meta.get("qa_id", "unknown")
        source = meta.get("source_title") or meta.get("source_url") or "unknown source"
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id: {qa_id} | source: {source} | relevance score: {score:.3f}")
        lines.append(doc.page_content)
        lines.append("")
    return "\n".join(lines)


def extract_answer(raw: str, strategy: str) -> str:
    """Strip CoT reasoning block and clean up the answer text."""
    if strategy == "cot_self":
        raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL).strip()
        if raw.startswith("Answer:"):
            raw = raw[len("Answer:"):].strip()
    result = raw.strip()
    return result if result else "No answer generated."


def build_rag_messages(
    system_prompt: str,
    context: str,
    question: str,
    few_shot_context: str = "",
) -> list[ChatMessage]:
    """Build system+user ChatMessage list for a RAG prompt."""
    effective_system = (
        f"{system_prompt}\n\n{few_shot_context}" if few_shot_context else system_prompt
    )
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=effective_system),
        ChatMessage(role=MessageRole.USER, content=f"{context}\n\n---\n\nQuestion: {question}"),
    ]


# ---------------------------------------------------------------------------
# WorkflowRunner: sync/async wrapper
# ---------------------------------------------------------------------------

class WorkflowRunner:
    """Thin wrapper providing synchronous invoke() and async ainvoke().

    Wraps a LlamaIndex Workflow so it exposes the same interface as the
    former LangGraph pipeline wrappers used by app.py and the registry.
    """

    def __init__(self, workflow: Any) -> None:
        self._wf = workflow

    async def ainvoke(self, inputs: dict) -> dict:
        """Async invocation — preferred from async contexts (e.g. Chainlit)."""
        return await self._wf.run(**inputs)

    def invoke(self, inputs: dict) -> dict:
        """Synchronous invocation — for eval scripts and tests."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.ainvoke(inputs))
        finally:
            loop.close()

    def __call__(self, inputs: dict) -> dict:
        return self.invoke(inputs)
