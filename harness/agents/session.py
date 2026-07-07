"""Assemble + run the full agentic session (config-driven, end-to-end).

``assemble_agent`` is the pure wiring (testable offline): it builds the query
transform + rerankers from a :class:`RetrievalPipelineConfig` and constructs the
FunctionAgent with ``ema_search`` bound to that pipeline. The runtime entry point
is :func:`harness.recipes.build_recipe` — the single composition path (F6); it
opens nothing here, the caller supplies the retriever + LLM. ``AgentSession.arun``
runs a query to a ``RegulatoryAnswer`` and optionally records an MLflow run.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from harness.agents.registry import build_agent
from harness.agents.runner import arun_agent
from harness.retrieval import build_postprocessors, get_transform
from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)


def assemble_agent(
    *,
    base_retriever: Any,
    llm: Any,
    agent_config: Any,
    pipeline_config: Any = None,
    acronyms: dict[str, str] | None = None,
    fetcher: Any = None,
) -> Any:
    """Wire a FunctionAgent whose ``ema_search`` runs the config-driven pipeline.

    Pure assembly — no index/LLM is opened here. Pass ``pipeline_config=None`` for a
    plain retrieve (no transform/rerank). ``agent_config`` (an ``AgentConfig``,
    normally derived from a recipe by ``build_recipe``) supplies the
    toolset/prompt/schema — there is no separate agent YAML (F6).
    """
    transform = None
    postprocessors: list = []
    if pipeline_config is not None:
        # acronyms=None lets the ``acronym`` transform load the shipped EMA
        # dictionary (configs/retrieval/acronyms.yaml) — an explicit mapping
        # (tests) overrides it.
        transform = get_transform(pipeline_config.query_transform, llm=llm, acronyms=acronyms)
        postprocessors = build_postprocessors(
            pipeline_config.rerank,
            top_n=pipeline_config.rerank_top_n,
            llm=llm,
            doc_type_priority=getattr(pipeline_config, "doc_type_priority", None),
        )
    return build_agent(
        llm=llm,
        config=agent_config,
        retriever=base_retriever,
        transform=transform,
        postprocessors=postprocessors,
        fetcher=fetcher,
    )


@dataclass
class AgentSession:
    """A ready-to-run agent + its resolved retrieval config."""

    agent: Any
    pipeline_config: Any = None
    experiment: str | None = None

    async def arun(
        self, query: str, *, record: bool = False, run_name: str | None = None
    ) -> RegulatoryAnswer:
        answer = await arun_agent(self.agent, query, pipeline_config=self.pipeline_config)
        if record:
            from harness.obs import default_experiment, record_answer_run, setup_mlflow

            # Ensure a usable MLflow backend exists before recording. setup_mlflow
            # pins the run to the local sqlite store (mlflow.db) — or MLFLOW_TRACKING_URI
            # if set — under the session experiment, the same store the live app serves.
            # Idempotent if setup_tracing already ran.
            setup_mlflow(self.experiment or default_experiment())
            params = self.pipeline_config.resolved_attributes() if self.pipeline_config else None
            record_answer_run(run_name or "agent_run", answer, params=params, query=query)
        return answer

    def run(self, query: str, **kwargs: Any) -> RegulatoryAnswer:
        return asyncio.run(self.arun(query, **kwargs))
