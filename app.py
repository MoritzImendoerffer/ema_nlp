"""
EMA Q&A Chat UI — Chainlit 2.11

Browser chat with hybrid RAG retrieval, streaming Claude synthesis,
Arize Phoenix trace integration, and per-step 👍/👎 feedback.

Usage:
    chainlit run app.py
    PHOENIX_DISABLED=1 chainlit run app.py      # tracing off
    EMA_INDEX_PATH=/path/to/index chainlit run app.py
    EMA_CORPUS_PATH=/path/to/corpus.jsonl chainlit run app.py
    EMA_CLAUDE_MODEL=claude-sonnet-4-6 chainlit run app.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import chainlit as cl
import opentelemetry.context as otel_ctx
import opentelemetry.trace as otel_trace
from dotenv import load_dotenv
from opentelemetry.trace import set_span_in_context

load_dotenv(Path.home() / ".myenvs" / "ema_nlp.env", override=False)

PHOENIX_URL = os.getenv("PHOENIX_URL", "http://localhost:6006")
PHOENIX_DISABLED = os.getenv("PHOENIX_DISABLED", "").lower() in ("1", "true", "yes")
CLAUDE_MODEL = os.getenv("EMA_CLAUDE_MODEL") or os.getenv("EMA_LLM_MODEL", "claude-haiku-4-5-20251001")
RETRIEVAL_K = 10
SOURCES_SHOWN = 5

log = logging.getLogger(__name__)

# ── Phoenix / OpenInference instrumentation ───────────────────────────────────
if not PHOENIX_DISABLED:
    try:
        import phoenix.otel as phoenix_otel
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

        phoenix_otel.register(
            project_name="ema-nlp",
            endpoint=f"{PHOENIX_URL}/v1/traces",
            set_global_provider=True,
            verbose=False,
        )
        LlamaIndexInstrumentor().instrument()
        AnthropicInstrumentor().instrument()
        log.info("Phoenix tracing → %s", PHOENIX_URL)
    except Exception as exc:
        log.warning("Phoenix setup failed (%s) — tracing disabled", exc)
        PHOENIX_DISABLED = True

_tracer = otel_trace.get_tracer("ema-nlp.app")

_NULL_SPAN_ID = "0" * 16


# ── Index loading (runs in a thread pool worker) ──────────────────────────────

def _load_index_sync():
    from harness.embed import DEFAULT_CORPUS as _DEFAULT_CORPUS
    from harness.embed import DEFAULT_INDEX_DIR as _DEFAULT_IDX
    from harness.embed import _configure_embed_model, build_index

    corpus_path = Path(os.getenv("EMA_CORPUS_PATH", str(_DEFAULT_CORPUS)))
    index_dir = Path(os.getenv("EMA_INDEX_PATH", str(_DEFAULT_IDX)))
    _configure_embed_model()
    return build_index(corpus_path=corpus_path, index_dir=index_dir)


# ── Chainlit lifecycle ────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content="Loading EMA Q&A index… (first run builds embeddings and may take ≤ 30 s)"
    ).send()
    try:
        index = await asyncio.to_thread(_load_index_sync)
    except Exception as exc:
        await cl.Message(content=f"Index load failed: {exc}").send()
        raise
    cl.user_session.set("index", index)
    await cl.Message(
        content="Ready. Ask any question about EMA human-regulatory guidance."
    ).send()


# ── Message handler ───────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message) -> None:
    index = cl.user_session.get("index")
    if index is None:
        await cl.Message(content="Index not loaded — please refresh.").send()
        return

    query = message.content.strip()
    if not query:
        return

    retrieval_span_id: str = _NULL_SPAN_ID
    synthesis_span_id: str = _NULL_SPAN_ID

    # ── Step 1: Retrieval ─────────────────────────────────────────────────────
    async with cl.Step(name="Retrieval", type="retrieval") as ret_step:
        ret_step.input = query

        def _do_retrieval():
            from harness.retrieve import retrieve
            with _tracer.start_as_current_span("ema-app.retrieval") as span:
                res = retrieve(index, query, mode="hybrid", k=RETRIEVAL_K)
                sid = format(span.get_span_context().span_id, "016x")
            return res, sid

        results, retrieval_span_id = await asyncio.to_thread(_do_retrieval)

        sources: list[dict[str, Any]] = []
        for qa_id, score, meta in results[:SOURCES_SHOWN]:
            node = index.docstore.get_node(qa_id)
            text = node.text if node else ""
            q_part, _, a_part = text.partition("\n\nA: ")
            sources.append(
                {
                    "score": score,
                    "question": q_part.removeprefix("Q: "),
                    "answer": a_part,
                    "topic_path": meta.get("topic_path", ""),
                    "source_url": meta.get("source_url", ""),
                }
            )

        top3 = ", ".join(f"{r[1]:.3f}" for r in results[:3])
        ret_step.output = f"Retrieved {len(results)} docs — top-3 scores: {top3}"

    # ── Source sidebar elements ───────────────────────────────────────────────
    source_elements: list[cl.Text] = []
    for i, src in enumerate(sources, 1):
        url = src["source_url"]
        link = f"[{url}]({url})" if url else "_no URL_"
        q = src["question"]
        short_q = q[:120] + ("…" if len(q) > 120 else "")
        card = (
            f"**{i}. {short_q}**\n\n"
            f"Score: `{src['score']:.3f}` · Topic: `{src['topic_path'] or '—'}`\n\n"
            f"Source: {link}"
        )
        source_elements.append(cl.Text(name=f"Source {i}", content=card, display="side"))

    # ── Step 2: Synthesis ─────────────────────────────────────────────────────
    context_block = "\n\n---\n\n".join(
        f"[{i}] Q: {s['question']}\nA: {s['answer']}" for i, s in enumerate(sources, 1)
    )
    system_prompt = (
        "You are an expert assistant for European Medicines Agency (EMA) "
        "regulatory Q&A. Answer based ONLY on the provided reference excerpts. "
        "If the excerpts lack sufficient information, say so explicitly. "
        "Cite excerpt numbers [1], [2] etc. when relevant."
    )
    user_prompt = (
        f"Reference excerpts from EMA regulatory documents:\n\n{context_block}\n\n"
        f"Question: {query}"
    )

    import anthropic

    synthesis_span = _tracer.start_span("ema-app.synthesis")
    token = otel_ctx.attach(set_span_in_context(synthesis_span))
    answer_msg = cl.Message(content="", elements=source_elements)
    usage_str = ""

    try:
        async with cl.Step(name="Synthesis", type="llm") as syn_step:
            syn_step.input = query

            async with anthropic.AsyncAnthropic().messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for chunk in stream.text_stream:
                    await answer_msg.stream_token(chunk)
                final = await stream.get_final_message()

            usage_str = (
                f"{final.usage.input_tokens} in / {final.usage.output_tokens} out tokens"
            )
            syn_step.output = f"Done ({usage_str})"
            synthesis_span_id = format(synthesis_span.get_span_context().span_id, "016x")
    finally:
        synthesis_span.end()
        otel_ctx.detach(token)

    # ── Final message ─────────────────────────────────────────────────────────
    if not PHOENIX_DISABLED:
        answer_msg.content += f"\n\n[View traces →]({PHOENIX_URL}/projects/ema-nlp)"

    await answer_msg.send()

    # Rating actions
    actions: list[cl.Action] = []
    if retrieval_span_id != _NULL_SPAN_ID:
        actions += [
            cl.Action(name="rate",
                      payload={"step": "retrieval", "span_id": retrieval_span_id, "rating": "good"},
                      label="👍 Retrieval"),
            cl.Action(name="rate",
                      payload={"step": "retrieval", "span_id": retrieval_span_id, "rating": "bad"},
                      label="👎 Retrieval"),
        ]
    if synthesis_span_id != _NULL_SPAN_ID:
        actions += [
            cl.Action(name="rate",
                      payload={"step": "synthesis", "span_id": synthesis_span_id, "rating": "good"},
                      label="👍 Answer"),
            cl.Action(name="rate",
                      payload={"step": "synthesis", "span_id": synthesis_span_id, "rating": "bad"},
                      label="👎 Answer"),
        ]
    if actions:
        await cl.Message(content="Rate this response:", actions=actions).send()


# ── Feedback callback ─────────────────────────────────────────────────────────

@cl.action_callback("rate")
async def on_rate(action: cl.Action) -> None:
    """Post 👍/👎 as a Phoenix span annotation."""
    payload = action.payload
    step_name = payload.get("step", "unknown")
    span_id = payload.get("span_id", "")
    rating = payload.get("rating", "")
    if not span_id or not rating:
        return

    label = "good" if rating == "good" else "bad"
    score = 1.0 if rating == "good" else 0.0

    if not PHOENIX_DISABLED:
        try:
            from phoenix.client import Client as PhoenixClient

            PhoenixClient(base_url=PHOENIX_URL).spans.add_span_annotation(
                span_id=span_id,
                annotation_name=f"user-rating-{step_name}",
                annotator_kind="HUMAN",
                label=label,
                score=score,
            )
        except Exception as exc:
            log.warning("Phoenix annotation failed: %s", exc)

    emoji = "👍" if rating == "good" else "👎"
    await cl.Message(content=f"{emoji} Recorded ({label}) for {step_name} step.").send()
