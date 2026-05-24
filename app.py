"""
EMA Q&A Chat UI — Chainlit 2.11

Browser chat with hybrid RAG retrieval, LlamaIndex Workflow pipeline,
Arize Phoenix trace integration, and per-step 👍/👎 feedback.

Each chat session builds a fresh WorkflowRunner (stateless per turn;
session context is managed by the cache, not by workflow state).

Usage:
    chainlit run app.py
    PHOENIX_DISABLED=1 chainlit run app.py           # tracing off
    EMA_INDEX_PATH=/path/to/index chainlit run app.py
    EMA_CORPUS_PATH=/path/to/corpus.jsonl chainlit run app.py
    EMA_WORKFLOW_STRATEGY=crag chainlit run app.py   # default: simple_rag_zero
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
from dotenv import load_dotenv

load_dotenv(Path.home() / ".myenvs" / "ema_nlp.env", override=False)

PHOENIX_URL = os.getenv("PHOENIX_URL", "http://localhost:6006")
PHOENIX_DISABLED = os.getenv("PHOENIX_DISABLED", "").lower() in ("1", "true", "yes")
WORKFLOW_STRATEGY = os.getenv("EMA_WORKFLOW_STRATEGY", "simple_rag_zero")
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


def _build_session_workflow(index: Any) -> Any:
    """Build a WorkflowRunner for a single browser session."""
    from harness.llms import get_llm
    from harness.retrieve import RetrievalConfig
    from harness.workflows.registry import get_workflow

    llm = get_llm("mid")
    cfg = RetrievalConfig(mode="hybrid", k=RETRIEVAL_K)
    return get_workflow(WORKFLOW_STRATEGY, index=index, llm=llm, retrieval_config=cfg)


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

    # Session identity — printed to server log and stored for MemorySaver thread_id
    session_id = str(uuid.uuid4())
    log.info("Session started: %s", session_id)
    cl.user_session.set("session_id", session_id)

    # Build LlamaIndex Workflow runner for this session
    pipeline = await asyncio.to_thread(_build_session_workflow, index)
    cl.user_session.set("pipeline", pipeline)

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


# ── Pipeline (one turn, stateless WorkflowRunner) ────────────────────────────

async def _run_pipeline(query: str, msg_num: int) -> None:
    from harness.fewshot_inject import get_fewshot_context
    from harness.query_cache import QueryCache

    pipeline: Any = cl.user_session.get("pipeline")
    cache: QueryCache | None = cl.user_session.get("cache")
    query_vec = await asyncio.to_thread(_embed_query_sync, query)

    # ── Cache lookup ──────────────────────────────────────────────────────────
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
                cl.Action(name="cache_pick", payload={"v": "skip"}, label="[c] Run full pipeline"),
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

    # ── LlamaIndex Workflow invocation ───────────────────────────────────────
    # Inject rated past examples as few-shot context (suppressed when < 3 rated entries exist)
    few_shot_block = (
        get_fewshot_context(query_vec, cache, k=3, min_rating=4) or ""
        if query_vec is not None
        else ""
    )

    async with cl.Step(name="Pipeline", type="run") as step:
        step.input = query
        result: dict = await pipeline.ainvoke(
            {"question": query, "few_shot_context": few_shot_block},
        )
        step.output = f"Done: {len(result.get('answer_text', ''))} chars"

    answer_text: str = result.get("answer_text", "No answer generated.")
    docs: list = result.get("docs", [])

    # ── Source sidebar elements ───────────────────────────────────────────────
    source_elements: list[cl.Text] = []
    for i, doc in enumerate(docs[:SOURCES_SHOWN], 1):
        meta = doc.metadata
        score = meta.get("score", 0.0)
        topic = meta.get("topic_path", "")
        url = meta.get("source_url", "")
        text = doc.text
        q_part, _, _ = text.partition("\n\nA: ")
        short_q = q_part.removeprefix("Q: ")[:120] + ("…" if len(q_part) > 120 else "")
        link = f"[{url}]({url})" if url else "_no URL_"
        card = (
            f"**Q{msg_num}·{i}. {short_q}**\n\n"
            f"Score: `{score:.3f}` · Topic: `{topic or '—'}`\n\n"
            f"Source: {link}"
        )
        source_elements.append(cl.Text(name=f"Q{msg_num} · Src {i}", content=card, display="side"))

    # ── Final message ─────────────────────────────────────────────────────────
    footer = f"\n\n[View traces →]({PHOENIX_URL}/projects/ema-nlp)" if not PHOENIX_DISABLED else ""
    await cl.Message(content=answer_text + footer, elements=source_elements).send()

    # ── Store in cache ────────────────────────────────────────────────────────
    if cache is not None and query_vec is not None and answer_text:
        run_id = str(uuid.uuid4())
        cited_ids = result.get("cited_qa_ids", [])
        await asyncio.to_thread(
            cache.add_entry,
            run_id,
            query,
            answer_text,
            cited_ids,
            query_vec,
        )
        cl.user_session.set("last_run_id", run_id)

    # ── Rating actions ────────────────────────────────────────────────────────
    await cl.Message(
        content="Rate this response:",
        actions=[
            cl.Action(name="rate", payload={"rating": "good", "run_id": cl.user_session.get("last_run_id", "")}, label="👍 Helpful"),
            cl.Action(name="rate", payload={"rating": "bad",  "run_id": cl.user_session.get("last_run_id", "")}, label="👎 Not helpful"),
        ],
    ).send()


# ── Message handler ───────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message) -> None:
    pipeline = cl.user_session.get("pipeline")
    if pipeline is None:
        await cl.Message(content="Pipeline not loaded — please refresh.").send()
        return

    query = message.content.strip()
    if not query:
        return

    msg_num = cl.user_session.get("msg_counter", 0) + 1
    cl.user_session.set("msg_counter", msg_num)

    await _run_pipeline(query, msg_num)


# ── Feedback callback ─────────────────────────────────────────────────────────

@cl.action_callback("rate")
async def on_rate(action: cl.Action) -> None:
    """Post 👍/👎 as a Phoenix span annotation by run_id."""
    payload = action.payload
    rating = payload.get("rating", "")
    run_id = payload.get("run_id", "")
    if not rating:
        return

    label = "good" if rating == "good" else "bad"
    score = 1.0 if rating == "good" else 0.0

    if not PHOENIX_DISABLED and run_id:
        try:
            from phoenix.client import Client as PhoenixClient

            from harness.rating import _find_recent_root_span_id

            client = PhoenixClient(base_url=PHOENIX_URL)
            span_id = _find_recent_root_span_id(client, "ema-nlp")
            if span_id:
                client.spans.add_span_annotation(
                    span_id=span_id,
                    annotation_name="user_rating",
                    annotator_kind="HUMAN",
                    label=label,
                    score=score,
                    metadata={"run_id": run_id},
                )
        except Exception as exc:
            log.warning("Phoenix annotation failed: %s", exc)

    emoji = "👍" if rating == "good" else "👎"
    await cl.Message(content=f"{emoji} Recorded ({label}).").send()
