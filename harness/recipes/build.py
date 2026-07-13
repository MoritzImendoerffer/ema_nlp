"""Build a runnable pipeline from a Recipe — the single composition path.

One engine: every recipe becomes a LlamaIndex ``FunctionAgent`` (via
``assemble_agent``), wrapped in ``AgentWorkflowAdapter`` so app.py / scripts / eval
all consume the uniform ``invoke``/``ainvoke`` → ``{answer_text, docs, answer}``
contract. The resolved recipe is stamped on the MLflow turn span for transparency.

``index`` (an opened LlamaIndex index for ``recipe.index_profile``) is passed in by the
caller — app.py opens and caches it — so a profile switch does not reopen Neo4j here.
"""

from __future__ import annotations

import logging
from typing import Any

from harness.recipes.config import Recipe

log = logging.getLogger(__name__)


def build_recipe(
    recipe: Recipe,
    index: Any,
    *,
    model: str | None = None,
    temperature: float | None = None,
    retrieval_k: int | None = None,
) -> Any:
    """Assemble the agent described by ``recipe`` over an opened ``index``.

    ``model``/``temperature``/``retrieval_k`` are optional live overrides (the settings
    panel) that take precedence over the recipe's defaults; everything else is fixed by
    the recipe. Returns an ``AgentWorkflowAdapter`` (the ``invoke``/``ainvoke`` contract).
    """
    from harness.agents.config import AgentConfig
    from harness.agents.session import AgentSession, assemble_agent
    from harness.agents.workflow_adapter import AgentWorkflowAdapter
    from harness.indexing import build_retriever, load_index_profile
    from harness.llms import get_llm_for_model

    profile = load_index_profile(recipe.index_profile)
    if retrieval_k:
        profile.retrieval.k = retrieval_k
    effective_k = profile.retrieval.k
    retriever = build_retriever(profile, index)
    effective_model = model or recipe.model
    effective_temp = temperature if temperature is not None else recipe.temperature
    llm = get_llm_for_model(effective_model, temperature_override=effective_temp)

    pipeline_config = None
    if recipe.pipeline:
        from harness.retrieval import load_pipeline_config

        pipeline_config = load_pipeline_config(recipe.pipeline)

    router = None
    if recipe.routing:
        from harness.retrieval import load_router

        router = load_router(recipe.routing)

    # The topic-subgraph layer (docs/next/topic_subgraphs.md) exists iff the
    # recipe's toolset names topic_context; the hubs file is loaded here (fail
    # loudly at build time, not on the first tool call).
    hubs = None
    if "topic_context" in recipe.tools:
        from harness.retrieval.hubs import load_hubs

        hubs = load_hubs(recipe.subgraph.hubs)

    # The recipe carries the agent-shaped fields inline (prompt/tools/schema), so we
    # construct an AgentConfig from it rather than loading a separate agent YAML.
    agent_config = AgentConfig(
        name=recipe.name,
        system_prompt=recipe.system_prompt,
        tools=recipe.tools,
        output_schema=recipe.output_schema,
        retrieval_profile=recipe.index_profile,
    )
    agent = assemble_agent(
        base_retriever=retriever,
        llm=llm,
        agent_config=agent_config,
        pipeline_config=pipeline_config,
        router=router,
        hubs=hubs,
        subgraph=recipe.subgraph,
    )
    log.info(
        "built recipe %r: tools=%s pipeline=%s routing=%s model=%s k=%s",
        recipe.name,
        recipe.tools,
        recipe.pipeline or "none",
        recipe.routing or "none",
        effective_model,
        effective_k,
    )
    session = AgentSession(agent=agent, pipeline_config=pipeline_config)
    # Stamp the EFFECTIVE config (override-applied), not the recipe defaults, so the trace
    # reflects what actually ran.
    attrs = recipe.resolved_attributes(
        model=effective_model, temperature=effective_temp, retrieval_k=effective_k
    )
    return AgentWorkflowAdapter(session, extra_attributes=attrs)
