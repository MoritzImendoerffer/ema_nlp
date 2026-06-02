"""
EMA Q&A Chat UI — Chainlit 2.11

Browser chat with hybrid RAG retrieval, LlamaIndex Workflow pipeline,
Arize Phoenix trace integration, and per-step 👍/👎 feedback.

Features:
  - Left sidebar:   persistent chat history (SQLite); login with UI_PASSWORD env var
  - Right sidebar:  model + parameter settings (model, temperature, k, cache toggle)
  - ChatProfile:    workflow strategy selector (9 LlamaIndex strategies)

Usage:
    chainlit run app.py
    PHOENIX_DISABLED=1 chainlit run app.py           # tracing off
    UI_PASSWORD=secret chainlit run app.py           # override login password (default: dev)
    EMA_WORKFLOW_STRATEGY=crag chainlit run app.py   # set default profile
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
WORKFLOW_STRATEGY = os.getenv("EMA_WORKFLOW_STRATEGY", "simple_rag")
EMA_INDEX_PROFILE = os.getenv("EMA_INDEX_PROFILE", "neo4j_hier")
RETRIEVAL_K = 10
SOURCES_SHOWN = 5

log = logging.getLogger(__name__)

# ── Workflow profile → (strategy, prompt_strategy) mapping ───────────────────

_PROFILE_STRATEGY: dict[str, tuple[str, str | None]] = {
    "Simple RAG (zero-shot)": ("simple_rag", "zero_shot"),
    "Simple RAG (few-shot)":  ("simple_rag", "few_shot"),
    "Simple RAG (CoT)":       ("simple_rag", "cot_self"),
    "ReAct":                  ("react",         None),
    "CRAG":                   ("crag",          None),
    "Summarize RAG":          ("summarize_rag", None),
    "CRAG + Summarize":       ("crag_summarize", None),
    "CRAG + Review":          ("crag_review",    None),
    "ReAct + Review":         ("react_review",   None),
}

_PROFILE_DESCRIPTIONS: dict[str, str] = {
    "simple_rag":    "Retrieve → generate (prompt variant set by profile)",
    "react":         "ReAct loop with per-step Phoenix spans",
    "crag":          "Retrieve → grade ⇄ rewrite → generate",
    "summarize_rag": "Retrieve → summarize → generate",
    "crag_summarize":"CRAG loop → summarize → generate",
    "crag_review":   "CRAG loop → generate → reviewer pass",
    "react_review":  "ReAct → reviewer (score only)",
}

# ── SQLite schema (created on first run via on_app_startup) ───────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT UNIQUE NOT NULL,
    "createdAt" TEXT,
    "metadata" TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT,
    "metadata" TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "parentId" TEXT,
    "name" TEXT,
    "type" TEXT,
    "command" TEXT,
    "modes" TEXT,
    "streaming" INTEGER,
    "waitForAnswer" INTEGER,
    "isError" INTEGER,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "defaultOpen" INTEGER,
    "autoCollapse" INTEGER,
    "language" TEXT,
    "icon" TEXT,
    "feedback" TEXT
);
CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "chainlitKey" TEXT,
    "path" TEXT,
    "url" TEXT,
    "objectKey" TEXT,
    "name" TEXT,
    "display" TEXT,
    "size" TEXT,
    "language" TEXT,
    "page" INTEGER,
    "props" TEXT,
    "autoPlay" INTEGER,
    "playerConfig" TEXT,
    "forId" TEXT,
    "mime" TEXT
);
CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT,
    "value" REAL,
    "threadId" TEXT,
    "comment" TEXT
);
"""

# ── Phoenix registration MUST come before any SDK imports ────────────────────
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


# Phoenix's UI uses base64-encoded node IDs in /projects/<id>, not raw names —
# resolve the ID lazily on first use (project is created server-side only after
# the first trace arrives) and cache it.
_PHOENIX_PROJECT_URL: str | None = None


async def _phoenix_project_url() -> str:
    global _PHOENIX_PROJECT_URL
    if _PHOENIX_PROJECT_URL:
        return _PHOENIX_PROJECT_URL

    def _fetch() -> str | None:
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(f"{PHOENIX_URL}/v1/projects", timeout=2) as r:
                for p in json.load(r).get("data", []):
                    if p.get("name") == "ema-nlp":
                        return f"{PHOENIX_URL}/projects/{p['id']}"
        except Exception as exc:
            log.warning("Phoenix project lookup failed: %s", exc)
        return None

    url = await asyncio.to_thread(_fetch)
    _PHOENIX_PROJECT_URL = url or f"{PHOENIX_URL}/projects"
    return _PHOENIX_PROJECT_URL


# ── Schema init (runs once at app startup) ────────────────────────────────────

@cl.on_app_startup
async def on_app_startup() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///chat_history.db")
    async with engine.begin() as conn:
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
    await engine.dispose()


# ── Auth + data layer ─────────────────────────────────────────────────────────

@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    expected = os.getenv("UI_PASSWORD", "dev")
    if password == expected:
        return cl.User(identifier=username, metadata={"role": "user"})
    return None


@cl.data_layer
def get_data_layer():
    from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
    return SQLAlchemyDataLayer("sqlite+aiosqlite:///chat_history.db")


# ── Chat profiles (workflow strategy selector) ────────────────────────────────

@cl.set_chat_profiles
async def set_chat_profiles(user: cl.User | None) -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(
            name=display_name,
            markdown_description=_PROFILE_DESCRIPTIONS.get(strategy, strategy),
            default=(strategy == WORKFLOW_STRATEGY),
        )
        for display_name, (strategy, _prompt_strategy) in _PROFILE_STRATEGY.items()
    ]


# ── Index loading ─────────────────────────────────────────────────────────────

def _load_index_sync():
    # Open the existing Neo4j PropertyGraphIndex selected by EMA_INDEX_PROFILE
    # (no rebuild / re-embed). configure_embed_model() also sets
    # Settings.embed_model so _embed_query_sync (semantic cache) works.
    from harness.indexing import load_index_profile
    from harness.indexing.property_graph import open_index
    from harness.providers import configure_embed_model

    configure_embed_model()
    profile = load_index_profile(EMA_INDEX_PROFILE)
    log.info("Loading index profile %s", profile.name)
    return open_index(profile)


def _embed_query_sync(query: str) -> np.ndarray | None:
    try:
        from llama_index.core import Settings
        vec = Settings.embed_model.get_text_embedding(query)
        return np.array(vec, dtype=np.float32)
    except Exception as exc:
        log.warning("Cache: embedding failed — %s", exc)
        return None


def _build_session_workflow(
    index: Any,
    *,
    strategy: str = WORKFLOW_STRATEGY,
    prompt_strategy: str | None = None,
    model_name: str = "claude_opus",
    temperature: float = 0.0,
    retrieval_k: int = RETRIEVAL_K,
) -> Any:
    from harness.indexing import load_index_profile
    from harness.indexing.registry import build_retriever
    from harness.llms import get_llm_for_model
    from harness.workflows.registry import get_workflow

    llm = get_llm_for_model(model_name, temperature_override=temperature)
    profile = load_index_profile(EMA_INDEX_PROFILE)
    if retrieval_k:
        profile.retrieval.k = retrieval_k
    retriever = build_retriever(profile, index)

    return get_workflow(
        strategy, retriever=retriever, llm=llm, prompt_strategy=prompt_strategy,
    )


# ── Settings helpers ──────────────────────────────────────────────────────────

def _make_chat_settings() -> cl.ChatSettings:
    return cl.ChatSettings([
        cl.input_widget.Select(
            id="agent_model",
            label="Agent model",
            values=["claude_haiku", "claude_opus", "olmo_32b", "local_qwen32"],
            initial_value="claude_opus",
        ),
        cl.input_widget.Slider(
            id="temperature", label="Temperature",
            min=0.0, max=1.0, step=0.05, initial=0.0,
        ),
        cl.input_widget.Slider(
            id="retrieval_k", label="Retrieval k",
            min=3, max=20, step=1, initial=float(RETRIEVAL_K),
        ),
        cl.input_widget.Switch(
            id="cache_enabled", label="Semantic cache", initial=True,
        ),
    ])


def _settings_to_pipeline_kwargs(settings: dict) -> dict:
    return {
        "model_name":  str(settings.get("agent_model", "claude_opus")),
        "temperature": float(settings.get("temperature", 0.0)),
        "retrieval_k": int(settings.get("retrieval_k", RETRIEVAL_K)),
    }


_DEFAULT_SETTINGS: dict = {
    "agent_model": "claude_opus",
    "temperature": 0.0,
    "retrieval_k": float(RETRIEVAL_K),
    "cache_enabled": True,
}


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

    session_id = str(uuid.uuid4())
    log.info("Session started: %s", session_id)

    profile_name = cl.user_session.get("chat_profile")
    strategy, prompt_strategy = _PROFILE_STRATEGY.get(profile_name or "", (WORKFLOW_STRATEGY, None))
    log.info("Strategy: %s prompt_strategy: %s (profile: %s)", strategy, prompt_strategy, profile_name)

    pipeline = await asyncio.to_thread(
        _build_session_workflow, index, strategy=strategy, prompt_strategy=prompt_strategy,
        **_settings_to_pipeline_kwargs(_DEFAULT_SETTINGS),
    )

    def _init_cache():
        from harness.query_cache import QueryCache
        return QueryCache()

    cache = await asyncio.to_thread(_init_cache)

    cl.user_session.set("session_id", session_id)
    cl.user_session.set("index", index)
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("cache", cache)
    cl.user_session.set("strategy", strategy)
    cl.user_session.set("prompt_strategy", prompt_strategy)
    cl.user_session.set("settings", _DEFAULT_SETTINGS.copy())
    cl.user_session.set("msg_counter", 0)

    await _make_chat_settings().send()
    await cl.Message(
        content="Ready. Ask any question about EMA human-regulatory guidance."
    ).send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict) -> None:
    # auto_tag_thread=true means the profile name is stored as a tag
    tags = thread.get("tags") or []
    profile_name = next((t for t in tags if t in _PROFILE_STRATEGY), None)
    strategy, prompt_strategy = _PROFILE_STRATEGY.get(profile_name or "", (WORKFLOW_STRATEGY, None))
    log.info("Resuming thread %s — strategy=%s prompt_strategy=%s", thread.get("id"), strategy, prompt_strategy)

    try:
        index = await asyncio.to_thread(_load_index_sync)
    except Exception as exc:
        await cl.Message(content=f"Index load failed on resume: {exc}").send()
        raise

    pipeline = await asyncio.to_thread(
        _build_session_workflow, index, strategy=strategy, prompt_strategy=prompt_strategy,
        **_settings_to_pipeline_kwargs(_DEFAULT_SETTINGS),
    )

    def _init_cache():
        from harness.query_cache import QueryCache
        return QueryCache()

    cache = await asyncio.to_thread(_init_cache)
    step_count = sum(
        1 for s in (thread.get("steps") or []) if s.get("type") == "user_message"
    )

    cl.user_session.set("session_id", thread["id"])
    cl.user_session.set("index", index)
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("cache", cache)
    cl.user_session.set("strategy", strategy)
    cl.user_session.set("prompt_strategy", prompt_strategy)
    cl.user_session.set("settings", _DEFAULT_SETTINGS.copy())
    cl.user_session.set("msg_counter", step_count)

    await _make_chat_settings().send()


# ── Settings update ───────────────────────────────────────────────────────────

@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    index = cl.user_session.get("index")
    if index is None:
        return

    strategy = cl.user_session.get("strategy", WORKFLOW_STRATEGY)
    prompt_strategy = cl.user_session.get("prompt_strategy")
    pipeline = await asyncio.to_thread(
        _build_session_workflow, index, strategy=strategy, prompt_strategy=prompt_strategy,
        **_settings_to_pipeline_kwargs(settings),
    )
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("settings", settings)

    cache_enabled = bool(settings.get("cache_enabled", True))
    if not cache_enabled:
        cl.user_session.set("cache", None)
    elif cl.user_session.get("cache") is None:
        def _init_cache():
            from harness.query_cache import QueryCache
            return QueryCache()
        cache = await asyncio.to_thread(_init_cache)
        cl.user_session.set("cache", cache)


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
    few_shot_block = (
        get_fewshot_context(query_vec, cache, k=3, min_rating=4) or ""
        if query_vec is not None
        else ""
    )

    run_id = str(uuid.uuid4())
    async with cl.Step(name="Pipeline", type="run") as step:
        step.input = query
        result: dict = await pipeline.ainvoke({
            "question": query,
            "few_shot_context": few_shot_block,
            "run_id": run_id,
            "source": "chainlit",
        })
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
        # Narrative chunks (no Q:/A: structure) — show a collapsed snippet of the
        # retrieved passage instead of parsing a question out of it.
        snippet = " ".join((doc.text or "").split())
        snippet = snippet[:240] + ("…" if len(snippet) > 240 else "")
        link = f"[{url}]({url})" if url else "_no URL_"
        card = (
            f"**Q{msg_num}·{i}**\n\n"
            f"Score: `{score:.3f}` · Topic: `{topic or '—'}`\n\n"
            f"Source: {link}\n\n"
            f"{snippet}"
        )
        source_elements.append(cl.Text(name=f"Q{msg_num} · Src {i}", content=card, display="side"))

    # ── Final message ─────────────────────────────────────────────────────────
    footer = f"\n\n[View traces →]({await _phoenix_project_url()})" if not PHOENIX_DISABLED else ""
    await cl.Message(content=answer_text + footer, elements=source_elements).send()

    # ── Store in cache ────────────────────────────────────────────────────────
    if cache is not None and query_vec is not None and answer_text:
        # Citations now key on retrieved-chunk source URLs (node metadata),
        # replacing the old cited_qa_ids the FAISS/pgvector path produced.
        cited_ids = [
            d.metadata.get("source_url")
            for d in docs[:SOURCES_SHOWN]
            if d.metadata.get("source_url")
        ]
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
