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
import uuid
from pathlib import Path
from typing import Any

import chainlit as cl
import numpy as np
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

# ── Phoenix registration MUST come before any SDK imports (anthropic, llama_index)
# so auto_instrument=True can patch them at import time, not after the fact.
if not PHOENIX_DISABLED:
    try:
        from phoenix.otel import register as _phoenix_register
        _phoenix_register(
            project_name="ema-nlp",
            auto_instrument=True,
            endpoint=f"{PHOENIX_URL}/v1/traces",
        )
        log.info("Phoenix tracing → %s", PHOENIX_URL)
    except Exception as exc:
        log.warning("Phoenix setup failed (%s) — tracing disabled", exc)
        PHOENIX_DISABLED = True

# SDK imports after registration so auto-instrumentation patches are in place
import anthropic

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


def _embed_query_sync(query: str) -> np.ndarray | None:
    """Embed a query string using the globally configured LlamaIndex embed model."""
    try:
        from llama_index.core import Settings
        vec = Settings.embed_model.get_text_embedding(query)
        return np.array(vec, dtype=np.float32)
    except Exception as exc:
        log.warning("Cache: embedding failed — %s", exc)
        return None


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

    # Initialise semantic cache — graceful if index dir doesn't exist yet
    def _init_cache():
        from harness.query_cache import QueryCache
        return QueryCache()

    cache = await asyncio.to_thread(_init_cache)
    cl.user_session.set("cache", cache)
    cl.user_session.set("msg_counter", 0)

    await cl.Message(
        content="Ready. Ask any question about EMA human-regulatory guidance."
    ).send()


# ── Pipeline (called inside a root OTel span) ─────────────────────────────────

async def _run_pipeline(query: str, msg_num: int, index: Any) -> None:
    # ── Cache lookup ──────────────────────────────────────────────────────────
    from harness.query_cache import CacheEntry, QueryCache

    cache: QueryCache | None = cl.user_session.get("cache")
    query_vec = await asyncio.to_thread(_embed_query_sync, query)

    few_shot_entry: CacheEntry | None = None  # populated if user picks "context" mode

    if cache is not None and query_vec is not None:
        cache_hits = cache.get_similar(query_vec, k=3)
        if cache_hits:
            lines = ["Similar past questions found:\n"]
            for i, (entry, sim) in enumerate(cache_hits):
                letter = chr(ord("a") + i)
                rating_str = f"{entry.rating:.1f}/5" if entry.rating is not None else "unrated"
                q_prev = entry.question_text[:100] + ("…" if len(entry.question_text) > 100 else "")
                a_prev = entry.answer_summary[:150] + ("…" if len(entry.answer_summary) > 150 else "")
                lines.append(
                    f"**[{letter}]** sim={sim:.2f} · rating={rating_str}\n"
                    f"Q: {q_prev}\n"
                    f"A: {a_prev}\n"
                )

            ask_actions = [
                cl.Action(
                    name="cache_pick",
                    payload={"v": f"use_{i}"},
                    label=f"[{chr(ord('a') + i)}] Use cached",
                )
                for i in range(len(cache_hits))
            ] + [
                cl.Action(name="cache_pick", payload={"v": "context"}, label="[c] Use as context + run fresh"),
                cl.Action(name="cache_pick", payload={"v": "skip"}, label="[d] Run full pipeline"),
            ]

            res = await cl.AskActionMessage(
                content="\n".join(lines),
                actions=ask_actions,
                timeout=60,
            ).send()

            choice: str = res["payload"].get("v", "skip") if res else "skip"

            if choice.startswith("use_"):
                idx = int(choice.split("_")[1])
                entry, sim = cache_hits[idx]
                await cl.Message(
                    content=f"*[Cached answer — similarity {sim:.2f}]*\n\n{entry.answer_summary}"
                ).send()
                return
            elif choice == "context":
                few_shot_entry = cache_hits[0][0]

    retrieval_span_id: str = _NULL_SPAN_ID
    synthesis_span_id: str = _NULL_SPAN_ID

    # ── Step 1: Retrieval ─────────────────────────────────────────────────────
    async with cl.Step(name="Retrieval", type="retrieval") as ret_step:
        ret_step.input = query

        def _do_retrieval():
            from harness.retrieve import RetrievalConfig, retrieve_with_config
            _ret_cfg = RetrievalConfig(
                strategy=os.getenv("EMA_RETRIEVAL_STRATEGY", "flat"),  # type: ignore[arg-type]
                mode=os.getenv("EMA_RETRIEVAL_MODE", "hybrid"),  # type: ignore[arg-type]
                k=RETRIEVAL_K,
            )
            with _tracer.start_as_current_span("ema-app.retrieval") as span:
                res = retrieve_with_config(_ret_cfg, index, query)
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
            f"**Q{msg_num}·{i}. {short_q}**\n\n"
            f"Score: `{src['score']:.3f}` · Topic: `{src['topic_path'] or '—'}`\n\n"
            f"Source: {link}"
        )
        source_elements.append(cl.Text(name=f"Q{msg_num} · Src {i}", content=card, display="side"))

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

    few_shot_block = ""
    if few_shot_entry is not None:
        few_shot_block = (
            f"\nExample of a similar past question and answer for context:\n"
            f"Q: {few_shot_entry.question_text}\n"
            f"A: {few_shot_entry.answer_summary}\n\n"
        )

    user_prompt = (
        f"{few_shot_block}"
        f"Reference excerpts from EMA regulatory documents:\n\n{context_block}\n\n"
        f"Question: {query}"
    )

    synthesis_span = _tracer.start_span("ema-app.synthesis")
    token = otel_ctx.attach(set_span_in_context(synthesis_span))
    answer_msg = cl.Message(content="", elements=source_elements)
    usage_str = ""
    answer_text = ""

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
                    answer_text += chunk
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

    # ── Store in cache ────────────────────────────────────────────────────────
    if cache is not None and query_vec is not None and answer_text:
        run_id = str(uuid.uuid4())
        cited_ids = [r[0] for r in results[:SOURCES_SHOWN]]
        await asyncio.to_thread(
            cache.add_entry,
            run_id,
            query,
            answer_text,
            cited_ids,
            query_vec,
        )
        cl.user_session.set("last_run_id", run_id)

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

    msg_num = cl.user_session.get("msg_counter", 0) + 1
    cl.user_session.set("msg_counter", msg_num)

    # Root OTel span groups retrieval + synthesis into a single trace in Phoenix.
    # try/finally ensures it is always closed, including early-return cache paths.
    root_span = _tracer.start_span("ema-app.request")
    root_span.set_attribute("query", query[:500])
    root_span.set_attribute("msg_num", msg_num)
    root_token = otel_ctx.attach(set_span_in_context(root_span))

    try:
        await _run_pipeline(query, msg_num, index)
    finally:
        root_span.end()
        otel_ctx.detach(root_token)


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
