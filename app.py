"""
EMA Q&A Chat UI — Chainlit 2.11

Browser chat with hybrid RAG retrieval, LlamaIndex Workflow pipeline,
MLflow trace integration, and per-turn 👍/👎 feedback (logged as MLflow trace
assessments). Traces + feedback are served by the MLflow UI (`run_ui.sh`).

Features:
  - Left sidebar:   persistent chat history (SQLite); login with UI_PASSWORD env var
  - Right sidebar:  live settings panel — a single Recipe selector (listed from the recipe
                    registry: harness/configs/recipes/*.yaml + $EMA_CONFIG_DIR) plus live
                    model/temperature/k/cache overrides. Changing the recipe rebuilds the
                    session pipeline in place.
  - ChatProfile:    seeds the initial recipe; the settings panel is the live source of truth.

Each recipe is one agent-centric pipeline (orchestration + retrieval + optional few-shot /
judge). See docs/RECIPES.md and docs/RAG_TECHNIQUES.md.

Usage:
    chainlit run app.py
    EMA_TRACING_DISABLED=1 chainlit run app.py       # tracing off
    UI_PASSWORD=secret chainlit run app.py           # override login password (default: dev)
    EMA_RECIPE=crag_agentic chainlit run app.py      # set the default recipe
    EMA_CONFIG_DIR=~/my_ema_configs chainlit run app.py   # add external recipes/prompts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import chainlit as cl
import numpy as np
from dotenv import load_dotenv

from harness.obs import default_experiment

load_dotenv(Path.home() / ".myenvs" / "ema_nlp.env", override=False)

# MLflow tracking server (writes traces/feedback) + UI URL (the "View traces" link).
# run_ui.sh starts `mlflow server` on :5000 backed by sqlite; both default there.
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_UI_URL = os.getenv("MLFLOW_UI_URL", "http://localhost:5000")
MLFLOW_EXPERIMENT = default_experiment()  # EMA_MLFLOW_EXPERIMENT env, shared resolver (F15)
TRACING_DISABLED = os.getenv("EMA_TRACING_DISABLED", "").lower() in ("1", "true", "yes")
DEFAULT_RECIPE = os.getenv("EMA_RECIPE", "")  # default recipe name; "" -> registry default
EMA_INDEX_PROFILE = os.getenv("EMA_INDEX_PROFILE", "neo4j_hier")
RETRIEVAL_K = 10
SOURCES_SHOWN = 5

log = logging.getLogger(__name__)

# ── Recipe selector (config-driven: recipes/*.yaml + $EMA_CONFIG_DIR) ─────────

def _model_choices() -> list[str]:
    """Model-override choices for the settings panel, read from models.yaml at render
    time (no hardcoded list to drift). The recipe sets the default; this lets a user
    swap the model live. Falls back to the common pair if models.yaml can't be read."""
    try:
        from harness.models import list_model_names

        return list_model_names() or ["claude_haiku", "claude_opus"]
    except Exception:
        return ["claude_haiku", "claude_opus"]


def _recipe_items() -> dict[str, str]:
    """``{recipe_name: label}`` for the dropdowns, read from the registry at render time
    so a recipe added to ``configs/recipes/`` or ``$EMA_CONFIG_DIR`` appears automatically."""
    from harness.recipes import load_all_recipes

    return {r.name: r.display_label for r in load_all_recipes()}


def _resolve_recipe_name(name: str | None) -> str:
    """A valid recipe name: the given one if known, else the env/registry default."""
    from harness.recipes import default_recipe_name, list_recipes

    names = list_recipes()
    if name and name in names:
        return name
    if DEFAULT_RECIPE and DEFAULT_RECIPE in names:
        return DEFAULT_RECIPE
    return default_recipe_name() or (names[0] if names else "")

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

# ── MLflow tracing setup ──────────────────────────────────────────────────────
# autolog instruments every LlamaIndex call, so each turn becomes one MLflow trace;
# the AgentWorkflowAdapter adds an explicit turn span that carries the resolved
# ema.* recipe config. Feedback (👍/👎) attaches to the trace below.
if not TRACING_DISABLED:
    try:
        from harness.obs import setup_tracing
        if setup_tracing(MLFLOW_EXPERIMENT, tracking_uri=MLFLOW_TRACKING_URI, autolog=True):
            log.info("MLflow tracing → %s (experiment=%s)", MLFLOW_TRACKING_URI, MLFLOW_EXPERIMENT)
        else:
            log.warning("MLflow unavailable — tracing disabled")
            TRACING_DISABLED = True
    except Exception as exc:
        log.warning("MLflow tracing setup failed (%s) — tracing disabled", exc)
        TRACING_DISABLED = True


# Deep link to the experiment's Traces tab in the MLflow UI. Resolving the
# experiment id is a tracking-server call, so resolve lazily and cache it.
_TRACES_URL: str | None = None


def _traces_url() -> str:
    global _TRACES_URL
    if _TRACES_URL:
        return _TRACES_URL
    from harness.obs import experiment_traces_url
    _TRACES_URL = experiment_traces_url(MLFLOW_UI_URL, MLFLOW_EXPERIMENT)
    return _TRACES_URL


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


class _LocalStorageClient:
    """Element persistence on the local filesystem (BaseStorageClient contract).

    Without a storage client, ``SQLAlchemyDataLayer.create_element`` silently
    drops every element — so the source cards vanished from resumed threads and
    their references could not be opened again. Files land under
    ``public/elements/`` which Chainlit serves at ``/public/...`` (gitignored).
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir.resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _path_for(self, object_key: str) -> Path:
        path = (self._base / object_key).resolve()
        if not path.is_relative_to(self._base):  # no escaping the elements dir
            raise ValueError(f"invalid element object key: {object_key!r}")
        return path

    async def upload_file(
        self,
        object_key: str,
        data: bytes | str,
        mime: str = "application/octet-stream",
        overwrite: bool = True,
        content_disposition: str | None = None,
    ) -> dict:
        path = self._path_for(object_key)
        if path.exists() and not overwrite:
            return {"object_key": object_key, "url": await self.get_read_url(object_key)}
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        await asyncio.to_thread(path.write_bytes, payload)
        return {"object_key": object_key, "url": await self.get_read_url(object_key)}

    async def delete_file(self, object_key: str) -> bool:
        try:
            self._path_for(object_key).unlink(missing_ok=True)
            return True
        except Exception:
            return False

    async def get_read_url(self, object_key: str) -> str:
        from urllib.parse import quote

        return "/public/elements/" + quote(object_key)

    async def close(self) -> None:
        return None


@cl.data_layer
def get_data_layer():
    from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

    return SQLAlchemyDataLayer(
        "sqlite+aiosqlite:///chat_history.db",
        # Persist message elements (the per-answer source cards) so they survive
        # a chat resume; see _LocalStorageClient.
        storage_provider=_LocalStorageClient(Path("public") / "elements"),
    )


# ── Chat profiles (recipe selector) ───────────────────────────────────────────

@cl.set_chat_profiles
async def set_chat_profiles(user: cl.User | None) -> list[cl.ChatProfile]:
    """One profile per recipe; exactly one is flagged default."""
    from harness.recipes import load_all_recipes

    recipes = load_all_recipes()  # parse once, derive the default from the same list
    explicit = next((r.name for r in recipes if r.default), None)
    default = explicit if (explicit and not DEFAULT_RECIPE) else _resolve_recipe_name(None)
    return [
        cl.ChatProfile(
            name=r.name,
            markdown_description=f"**{r.display_label}** — {r.description or r.name}",
            default=(r.name == default),
        )
        for r in recipes
    ]


# ── Index loading ─────────────────────────────────────────────────────────────

def _load_index_sync(profile_name: str) -> Any:
    """Open (no rebuild) the index for ``profile_name`` via the registry dispatch,
    so a non-property_graph profile loads its own store. ``open_index`` also sets
    ``Settings.embed_model`` (used by the semantic-cache query embedding). Keeps
    ``EMA_INDEX_PROFILE`` in the env for code that resolves the default profile
    from the environment."""
    from harness.indexing import load_index_profile, open_index

    profile = load_index_profile(profile_name)
    log.info("Loading index profile %s", profile.name)
    index = open_index(profile)
    # Only after the open succeeds. On a FAILED switch the env stays on the old
    # profile. (Turn spans stamp the SESSION's profile, not this process-global
    # env — concurrent sessions must not mis-stamp each other, F13.)
    os.environ["EMA_INDEX_PROFILE"] = profile_name
    return index


def _embed_query_sync(query: str) -> np.ndarray | None:
    try:
        from llama_index.core import Settings
        vec = Settings.embed_model.get_text_embedding(query)
        return np.array(vec, dtype=np.float32)
    except Exception as exc:
        log.warning("Cache: embedding failed — %s", exc)
        return None


def _build_pipeline_sync(
    index: Any,
    recipe_name: str,
    *,
    model: str = "claude_opus",
    temperature: float = 0.0,
    retrieval_k: int = RETRIEVAL_K,
) -> Any:
    """Build the recipe's agent pipeline over ``index`` (model/temp/k are live overrides)."""
    from harness.recipes import build_recipe, get_recipe

    return build_recipe(
        get_recipe(recipe_name),
        index,
        model=model,
        temperature=temperature,
        retrieval_k=retrieval_k,
    )


# ── Settings helpers ──────────────────────────────────────────────────────────

def _make_chat_settings(current: dict) -> cl.ChatSettings:
    """Build the settings panel: a Recipe selector (from the registry) + live overrides.
    Every widget is seeded from ``current`` — a (re)render resets ALL widgets to their
    ``initial``, so passing the full current state avoids snapping others to defaults."""
    items = _recipe_items()
    recipe_initial = current.get("recipe") or _resolve_recipe_name(None)
    return cl.ChatSettings([
        cl.input_widget.Select(
            id="recipe", label="Recipe",
            items=items or {recipe_initial: recipe_initial},
            initial_value=recipe_initial,
        ),
        cl.input_widget.Select(
            id="model", label="Model (override)",
            values=_model_choices(),
            initial_value=str(current.get("model", "claude_opus")),
        ),
        cl.input_widget.Slider(
            id="temperature", label="Temperature",
            min=0.0, max=1.0, step=0.05, initial=float(current.get("temperature", 0.0)),
        ),
        cl.input_widget.Slider(
            id="retrieval_k", label="Retrieval k",
            min=3, max=20, step=1, initial=float(current.get("retrieval_k", RETRIEVAL_K)),
        ),
        cl.input_widget.Switch(
            id="cache_enabled", label="Semantic cache",
            initial=bool(current.get("cache_enabled", True)),
        ),
    ])


def _settings_to_kwargs(settings: dict) -> dict:
    """Map raw widget values → _build_pipeline_sync kwargs (recipe + live overrides)."""
    return {
        "recipe_name": _resolve_recipe_name(str(settings.get("recipe", ""))),
        "model":       str(settings.get("model", "claude_opus")),
        "temperature": float(settings.get("temperature", 0.0)),
        "retrieval_k": int(settings.get("retrieval_k", RETRIEVAL_K)),
    }


def _seed_settings(recipe_name: str) -> dict:
    """Initial settings dict — the ChatProfile seeds the recipe; model/temperature default
    to the recipe's own values; the panel is the live source of truth thereafter."""
    model, temperature = "claude_opus", 0.0
    try:
        from harness.recipes import get_recipe

        r = get_recipe(recipe_name)
        model, temperature = r.model, r.temperature
    except Exception:
        pass
    return {
        "recipe": recipe_name,
        "model": model,
        "temperature": temperature,
        "retrieval_k": float(RETRIEVAL_K),
        "cache_enabled": True,
    }


def _init_cache_sync():
    # Process-wide shared instance: separate per-session instances clobber each
    # other's entries/ratings on save (F4). The LIVE embedder's model name is
    # recorded as vector provenance — on a model switch the cache starts fresh
    # instead of silently mixing embedding spaces (F12). Settings.embed_model is
    # configured by open_index (from the index profile) before this runs.
    from llama_index.core import Settings

    from harness.query_cache import get_query_cache

    embed_model = getattr(getattr(Settings, "embed_model", None), "model_name", None)
    return get_query_cache(embed_model=embed_model)


# ── Chainlit lifecycle ────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content="Loading EMA Q&A index… (first run builds embeddings and may take ≤ 30 s)"
    ).send()

    from harness.recipes import get_recipe

    recipe_name = _resolve_recipe_name(cl.user_session.get("chat_profile"))
    recipe = get_recipe(recipe_name)
    seed = _seed_settings(recipe_name)
    log.info("Recipe: %s (index_profile=%s)", recipe_name, recipe.index_profile)

    try:
        index = await asyncio.to_thread(_load_index_sync, recipe.index_profile)
    except Exception as exc:
        await cl.Message(content=f"Index load failed: {exc}").send()
        raise

    session_id = str(uuid.uuid4())
    log.info("Session started: %s", session_id)

    pipeline = await asyncio.to_thread(
        _build_pipeline_sync, index, recipe_name,
        model=seed["model"], temperature=float(seed["temperature"]),
        retrieval_k=int(seed["retrieval_k"]),
    )
    cache = await asyncio.to_thread(_init_cache_sync)

    cl.user_session.set("session_id", session_id)
    cl.user_session.set("index", index)
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("cache", cache)
    cl.user_session.set("recipe", recipe)
    cl.user_session.set("recipe_name", recipe_name)
    cl.user_session.set("index_profile", recipe.index_profile)
    cl.user_session.set("settings", seed)
    cl.user_session.set("msg_counter", 0)

    await _make_chat_settings(seed).send()
    await cl.Message(
        content=f"Ready — recipe **{recipe.display_label}**. "
        "Ask any question about EMA human-regulatory guidance."
    ).send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict) -> None:
    # auto_tag_thread is disabled (it breaks thread persistence on the SQLite data layer —
    # see .chainlit/config.toml), so the panel's recipe choice is not persisted per thread.
    # Best effort (F19): restore the recipe from the thread's chat_profile metadata (the
    # profile that seeded it); if none, fall back to the default — and SAY so either way,
    # instead of silently reverting a non-default thread.
    from harness.recipes import get_recipe

    meta = thread.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    recipe_name = _resolve_recipe_name(meta.get("chat_profile") if isinstance(meta, dict) else None)
    recipe = get_recipe(recipe_name)
    seed = _seed_settings(recipe_name)
    log.info("Resuming thread %s — recipe=%s", thread.get("id"), recipe_name)

    try:
        index = await asyncio.to_thread(_load_index_sync, recipe.index_profile)
    except Exception as exc:
        await cl.Message(content=f"Index load failed on resume: {exc}").send()
        raise

    pipeline = await asyncio.to_thread(
        _build_pipeline_sync, index, recipe_name,
        model=seed["model"], temperature=float(seed["temperature"]),
        retrieval_k=int(seed["retrieval_k"]),
    )
    cache = await asyncio.to_thread(_init_cache_sync)
    step_count = sum(
        1 for s in (thread.get("steps") or []) if s.get("type") == "user_message"
    )

    cl.user_session.set("session_id", thread["id"])
    cl.user_session.set("index", index)
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("cache", cache)
    cl.user_session.set("recipe", recipe)
    cl.user_session.set("recipe_name", recipe_name)
    cl.user_session.set("index_profile", recipe.index_profile)
    cl.user_session.set("settings", seed)
    cl.user_session.set("msg_counter", step_count)

    await _make_chat_settings(seed).send()
    await cl.Message(
        content=f"Resumed with recipe **{recipe.display_label}**. Mid-thread recipe changes "
        "are not persisted — re-select in Settings if this thread used a different one."
    ).send()


# ── Settings update ───────────────────────────────────────────────────────────

@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    index = cl.user_session.get("index")
    if index is None:
        return

    from harness.recipes import get_recipe

    kwargs = _settings_to_kwargs(settings)
    recipe = get_recipe(kwargs["recipe_name"])
    new_profile = recipe.index_profile
    old_profile = cl.user_session.get("index_profile", EMA_INDEX_PROFILE)

    # Reload the index ONLY when the recipe's retrieval profile changed — avoids reloading
    # Neo4j + re-instantiating the embed model on every settings save (GPU-friendly).
    if new_profile != old_profile:
        await cl.Message(
            content=f"Switching retrieval profile → `{new_profile}` (reloading index…)"
        ).send()
        try:
            index = await asyncio.to_thread(_load_index_sync, new_profile)
        except Exception as exc:
            # Keep session state AND the panel consistent with what actually runs:
            # snap the widgets back to the previous settings so the UI does not show
            # a recipe/profile that failed to load (F19).
            prev = cl.user_session.get("settings") or _seed_settings(
                cl.user_session.get("recipe_name", _resolve_recipe_name(None))
            )
            await cl.Message(
                content=f"Profile switch failed: {exc} — keeping `{old_profile}` and the "
                "previous recipe."
            ).send()
            await _make_chat_settings(prev).send()
            return
        cl.user_session.set("index", index)
        cl.user_session.set("index_profile", new_profile)

    pipeline = await asyncio.to_thread(
        _build_pipeline_sync, index, kwargs["recipe_name"],
        model=kwargs["model"], temperature=kwargs["temperature"], retrieval_k=kwargs["retrieval_k"],
    )
    prev_settings = cl.user_session.get("settings") or {}
    cl.user_session.set("pipeline", pipeline)
    cl.user_session.set("recipe", recipe)
    cl.user_session.set("recipe_name", kwargs["recipe_name"])
    cl.user_session.set("settings", settings)

    # Cache toggle semantics (F19): OFF disables cache *reads* (reuse offers + few-shot
    # injection) only — new answers and 👍/👎 ratings keep persisting so the learning
    # signal never silently stops accruing. The gate is read from session settings in
    # _run_pipeline; the cache instance itself stays available.
    if cl.user_session.get("cache") is None:
        cache = await asyncio.to_thread(_init_cache_sync)
        cl.user_session.set("cache", cache)
    cache_enabled = bool(settings.get("cache_enabled", True))
    was_enabled = bool(prev_settings.get("cache_enabled", True))
    if was_enabled and not cache_enabled:
        await cl.Message(
            content="Semantic cache reuse + few-shot injection **off** — new answers and "
            "👍/👎 ratings are still recorded."
        ).send()


# ── Pipeline (one turn, stateless AgentWorkflowAdapter.ainvoke) ──────────────

async def _run_pipeline(query: str, msg_num: int) -> None:
    from harness.fewshot_inject import get_fewshot_context
    from harness.obs import last_trace_id, record_answer_on_span, traced
    from harness.query_cache import QueryCache

    pipeline: Any = cl.user_session.get("pipeline")
    cache: QueryCache | None = cl.user_session.get("cache")
    # Cache toggle gates READS only (reuse offers + few-shot); writes always persist (F19).
    cache_reads = bool((cl.user_session.get("settings") or {}).get("cache_enabled", True))
    run_id = str(uuid.uuid4())
    trace_id = ""
    result: dict = {}

    # One MLflow trace per turn: the cache-lookup embedding, retrieval, and
    # generation all nest under this single root span. Without it the standalone
    # cache-lookup embedding (autolog-instrumented, run before the workflow) opens
    # its own *second* trace for every prompt.
    with traced(
        "chat.turn",
        attributes={
            "ema.run.id": run_id,
            "ema.run.source": "chainlit",
            # The SESSION's profile, not the process-global env — a concurrent
            # session's profile switch must not mis-stamp this turn (F13).
            "ema.index.profile": cl.user_session.get(
                "index_profile", os.getenv("EMA_INDEX_PROFILE", "neo4j_hier")
            ),
        },
    ) as turn_span:
        if turn_span is not None:
            try:
                turn_span.set_inputs({"question": query})
            except Exception:
                pass

        query_vec = await asyncio.to_thread(_embed_query_sync, query)

        # ── Cache lookup ──────────────────────────────────────────────────────
        if cache is not None and cache_reads and query_vec is not None:
            # Offer only entries not rated bad: 👎 (1.0) answers must not be
            # recycled; unrated entries stay eligible (F19).
            cache_hits = [
                (entry, sim)
                for entry, sim in cache.get_similar(query_vec, k=3)
                if entry.rating is None or entry.rating >= 4.0
            ]
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
                    record_answer_on_span(
                        turn_span, answer={"answer": entry.answer_summary, "source": "cache"}
                    )
                    # Allow re-rating the reused entry (feeds the few-shot cache); cache-only,
                    # so it targets the ORIGINAL entry and writes no trace assessment.
                    await cl.Message(
                        content="Rate this cached response:",
                        actions=[
                            cl.Action(name="rate", payload={"rating": "good", "run_id": entry.run_id, "cache_only": True}, label="👍 Helpful"),
                            cl.Action(name="rate", payload={"rating": "bad", "run_id": entry.run_id, "cache_only": True}, label="👎 Not helpful"),
                        ],
                    ).send()
                    return

        # ── Recipe-gated few-shot injection ───────────────────────────────────
        recipe = cl.user_session.get("recipe")
        fewshot = getattr(recipe, "fewshot", None)
        few_shot_block = ""
        if fewshot is not None and fewshot.enabled and cache_reads and query_vec is not None:
            few_shot_block = (
                get_fewshot_context(
                    query_vec,
                    cache,
                    k=fewshot.k,
                    min_rating=fewshot.min_rating,
                    min_examples=fewshot.min_examples,
                )
                or ""
            )

        async with cl.Step(name="Pipeline", type="run") as step:
            step.input = query
            result = await pipeline.ainvoke({
                "question": query,
                "few_shot_context": few_shot_block,
                "run_id": run_id,
                "source": "chainlit",
            })
            step.output = f"Done: {len(result.get('answer_text', ''))} chars"

        record_answer_on_span(turn_span, answer=result.get("answer"))

        answer_text = result.get("answer_text", "No answer generated.")
        docs = result.get("docs", [])

        # ── Optional inline judge layer (recipe.judge) ────────────────────────
        # Run INSIDE the turn span so the judge's LLM call nests under this trace (no
        # second trace per turn); feedback is logged after the span closes, when the
        # trace id is available. Faithfulness is graded against the FULL retrieved
        # passages (context_passages) when the agent surfaced them, else citation text.
        judge_note = ""
        judge_results: list = []
        judge_policy = getattr(recipe, "judge", None)
        if judge_policy is not None and judge_policy.enabled and answer_text and docs:
            from harness.eval import review_verdict, run_inline_judges

            context_passages = result.get("context_passages") or [
                d.text for d in docs if getattr(d, "text", "")
            ]
            judge_results = await asyncio.to_thread(
                run_inline_judges,
                judge_policy.judges,
                question=query,
                answer=answer_text,
                context_passages=context_passages,
                model_role=judge_policy.model_role,
            )
            if judge_results:
                judge_note = "\n\n_Judge: " + ", ".join(
                    f"{r.name} {r.score}/5" for r in judge_results
                ) + "_"
            # Soft reviewer gate (F18, advisory): a below-threshold (or unscorable)
            # answer ships WITH a visible caution note — never blocked. The verdict
            # is stamped on the turn span so traces are filterable by outcome.
            if judge_policy.threshold is not None:
                passed, review_note = review_verdict(judge_results, judge_policy.threshold)
                judge_note += review_note
                if turn_span is not None:
                    try:
                        turn_span.set_attributes({
                            "ema.judge.threshold": judge_policy.threshold,
                            "ema.judge.passed": passed,
                        })
                    except Exception:
                        pass

        # Certainty of the answer, visible in the final message (R1-Q3): the agent's
        # structured self-assessed confidence, when present.
        confidence = getattr(result.get("answer"), "confidence", None)
        if isinstance(confidence, (int, float)) and confidence > 0:
            judge_note += f"\n\n_Model confidence: {confidence:.2f}_"

    # Trace id of the turn just traced (read after the span closes).
    if not TRACING_DISABLED:
        trace_id = last_trace_id() or ""

    # Log judge assessments to the now-flushed turn trace (alongside the 👍/👎).
    if judge_results and not TRACING_DISABLED and trace_id:
        from harness.obs import log_judge_feedback

        for r in judge_results:
            await asyncio.to_thread(
                log_judge_feedback,
                trace_id,
                name=f"judge_{r.name}",
                value=r.value,
                rationale=r.rationale,
                metadata={"score": r.score, "run_id": run_id},
            )

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
    # The element NAMES must appear in the message content: Chainlit renders each
    # occurrence as a clickable reference that (re)opens the element side panel.
    # Without them the panel only auto-opens once per new element set — after
    # closing it (or resuming a thread) there is nothing to click.
    sources_line = ""
    if source_elements:
        sources_line = "\n\n**Sources:** " + " | ".join(e.name for e in source_elements)
    footer = ""
    if not TRACING_DISABLED:
        traces_link = await asyncio.to_thread(_traces_url)
        footer = f"\n\n[View traces →]({traces_link})"
    await cl.Message(
        content=answer_text + judge_note + sources_line + footer, elements=source_elements
    ).send()

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
    cl.user_session.set("last_trace_id", trace_id)

    # ── Rating actions ────────────────────────────────────────────────────────
    # Carry the trace id in the payload so the 👍/👎 maps to this exact turn's trace.
    await cl.Message(
        content="Rate this response:",
        actions=[
            cl.Action(name="rate", payload={"rating": "good", "run_id": run_id, "trace_id": trace_id}, label="👍 Helpful"),
            cl.Action(name="rate", payload={"rating": "bad",  "run_id": run_id, "trace_id": trace_id}, label="👎 Not helpful"),
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
    # A cache-only rating (reused cached answer) updates just the cache entry — there is
    # no fresh turn trace, so do NOT fall back to last_trace_id (that's a stale, prior turn).
    cache_only = bool(payload.get("cache_only", False))
    trace_id = "" if cache_only else (payload.get("trace_id", "") or cl.user_session.get("last_trace_id", ""))
    if not rating:
        return

    label = "good" if rating == "good" else "bad"

    # Persist the rating into the semantic cache so rated-trajectory few-shot injection
    # can use it: good->5, bad->1 on the 1-5 scale get_fewshot_context filters on
    # (min_rating). The cache entry was stored under this run_id during _run_pipeline.
    # (Injection itself stays gated by recipe config — see Phase 3.)
    cache = cl.user_session.get("cache")
    if cache is not None and run_id:
        await asyncio.to_thread(cache.update_rating, run_id, 5.0 if rating == "good" else 1.0)

    if not TRACING_DISABLED and trace_id:
        # Log as an MLflow trace assessment (👍=True / 👎=False). Done off-loop:
        # log_user_feedback flushes the async trace export then writes over HTTP.
        from harness.obs import log_user_feedback
        await asyncio.to_thread(
            log_user_feedback,
            trace_id,
            value=(rating == "good"),
            name="user_rating",
            rationale=None,
            metadata={"run_id": run_id, "label": label},
        )

    emoji = "👍" if rating == "good" else "👎"
    await cl.Message(content=f"{emoji} Recorded ({label}).").send()
