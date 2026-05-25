"""
Shared utilities for LlamaIndex workflow steps.

Provides:
  - load_system_prompt()   read prompt from harness/prompts/
  - results_to_docs()      convert RetrievalResult tuples to TextNode objects
  - format_docs()          render TextNode list as a formatted context string
  - extract_answer()       strip CoT reasoning block from raw LLM output
  - build_rag_messages()   construct system+user ChatMessage list for RAG prompts
  - WorkflowRunner         thin sync/async wrapper for LlamaIndex Workflow instances
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.schema import TextNode

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_PROMPT_FILES: dict[str, str] = {
    "zero_shot": "system_zero_shot.md",
    "few_shot": "system_few_shot_sme.md",
    "cot_self": "system_cot_self.md",
}


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

def results_to_docs(results: list, index: Any) -> list:
    """Convert (qa_id, score, metadata) triples to TextNode objects.

    Two paths:
      * pgvector — metadata already carries the chunk text under ``"text"``
        (populated by ``harness.pg.adapter.row_to_result``); use it directly.
      * FAISS — fall back to ``harness.embed.get_node_by_id(index, qa_id)``
        on the docstore. Requires ``index`` to be non-None.
    """
    nodes: list[TextNode] = []
    for qa_id, score, meta in results:
        text_in_meta = meta.get("text")
        if text_in_meta:
            md = {k: v for k, v in meta.items() if k != "text"}
            md["qa_id"] = qa_id
            md["score"] = score
            nodes.append(TextNode(text=text_in_meta, metadata=md))
            continue

        node = None
        if index is not None:
            from harness.embed import get_node_by_id
            node = get_node_by_id(index, qa_id)

        if node is not None:
            merged = {**node.metadata, **meta, "qa_id": qa_id, "score": score}
            nodes.append(TextNode(text=node.text, metadata=merged))
        else:
            nodes.append(TextNode(
                text=f"[qa_id: {qa_id}]",
                metadata={**meta, "qa_id": qa_id, "score": score},
            ))
    return nodes


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_docs(nodes: list) -> str:
    if not nodes:
        return "No relevant documents retrieved."
    lines: list[str] = ["## Retrieved Q&A documents", ""]
    for i, node in enumerate(nodes, 1):
        meta = node.metadata
        qa_id = meta.get("qa_id", "unknown")
        source = meta.get("source_title") or meta.get("source_url") or "unknown source"
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id: {qa_id} | source: {source} | relevance score: {score:.3f}")
        lines.append(node.text)
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

    Wraps a LlamaIndex Workflow so it exposes a uniform invoke/ainvoke
    interface used by app.py and the workflow registry.
    """

    _warned_no_config_attrs: set[str] = set()

    def __init__(self, workflow: Any) -> None:
        self._wf = workflow

    def _stamp_span(self, inputs: dict) -> None:
        """Stamp workflow config attributes onto the current OTel span (silent no-op if disabled)."""
        try:
            import opentelemetry.trace as otel_trace
            span = otel_trace.get_current_span()
            if not span.is_recording():
                return
            config_fn = getattr(self._wf, "config_attributes", None)
            if config_fn is None:
                wf_name = type(self._wf).__name__
                if wf_name not in WorkflowRunner._warned_no_config_attrs:
                    log.warning(
                        "Workflow %s has no config_attributes() — skipping span stamp", wf_name
                    )
                    WorkflowRunner._warned_no_config_attrs.add(wf_name)
            else:
                for k, v in config_fn().items():
                    span.set_attribute(k, v)
            if run_id := inputs.get("run_id"):
                span.set_attribute("ema.run.id", str(run_id))
            if source := inputs.get("source"):
                span.set_attribute("ema.run.source", str(source))
            span.set_attribute(
                "ema.retrieval.backend",
                os.getenv("EMA_RETRIEVER", "faiss").lower(),
            )
        except Exception:
            pass  # Phoenix disabled or OTel not installed — never raise from here

    async def ainvoke(self, inputs: dict) -> dict:
        """Async invocation — preferred from async contexts (e.g. Chainlit).

        Opens an explicit OTel span so the `ema.*` config attributes have a
        recording span to land on. LlamaIndex auto-instrumentation's own
        workflow spans become children of this one. When Phoenix is disabled
        (no-op tracer), `start_as_current_span` returns a non-recording span
        and `_stamp_span` silently no-ops, matching the previous behaviour.
        """
        try:
            import opentelemetry.trace as otel_trace
            tracer = otel_trace.get_tracer("ema_nlp.workflow")
            wf_name = type(self._wf).__name__
            with tracer.start_as_current_span(f"{wf_name}.invoke"):
                self._stamp_span(inputs)
                return await self._wf.run(**inputs)
        except ImportError:
            # OTel not installed at all — run without tracing
            self._stamp_span(inputs)
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
