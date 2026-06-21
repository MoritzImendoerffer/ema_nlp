"""Assemble + run the full agentic session (config-driven, end-to-end).

``assemble_agent`` is the pure wiring (testable offline): it builds the query
transform + rerankers from a :class:`RetrievalPipelineConfig` and constructs the
FunctionAgent with ``ema_search`` bound to that pipeline. ``build_session`` is the
runtime entry point — it opens the Neo4j index, builds the base retriever via the
existing ``harness.indexing`` pipeline, builds the LLM, and wires the agent
(verified live on the GPU host). ``AgentSession.arun`` runs a query to a
``RegulatoryAnswer`` and optionally records an MLflow run.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.agents.registry import build_agent
from harness.agents.runner import arun_agent
from harness.retrieval import build_postprocessors, get_transform, load_pipeline_config
from harness.schemas import RegulatoryAnswer

log = logging.getLogger(__name__)

_ACRONYM_DICT = Path("ablations/A_evidence_filter/acronym_dict.yaml")


def _load_default_acronyms() -> dict[str, str]:
    """Best-effort load of the project acronym dictionary (empty if absent)."""
    try:
        import yaml

        if _ACRONYM_DICT.exists():
            data = yaml.safe_load(_ACRONYM_DICT.read_text(encoding="utf-8")) or {}
            # accept either {acr: full} or {"acronyms": {acr: full}}
            return dict(data.get("acronyms", data)) if isinstance(data, dict) else {}
    except Exception as exc:
        log.debug("acronym dict load failed: %s", exc)
    return {}


def assemble_agent(
    *,
    base_retriever: Any,
    llm: Any,
    agent_name: str = "regulatory",
    pipeline_config: Any = None,
    acronyms: dict[str, str] | None = None,
    fetcher: Any = None,
) -> Any:
    """Wire a FunctionAgent whose ``ema_search`` runs the config-driven pipeline.

    Pure assembly — no index/LLM is opened here. Pass ``pipeline_config=None`` for a
    plain retrieve (no transform/rerank).
    """
    transform = None
    postprocessors: list = []
    if pipeline_config is not None:
        transform = get_transform(pipeline_config.query_transform, llm=llm, acronyms=acronyms or {})
        postprocessors = build_postprocessors(
            pipeline_config.rerank, top_n=pipeline_config.rerank_top_n, llm=llm
        )
    return build_agent(
        agent_name,
        llm=llm,
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
            from harness.obs import record_answer_run, setup_mlflow

            # Ensure a usable MLflow backend exists before recording. Without this,
            # record=True with enable_tracing=False (no prior setup_tracing) falls back
            # to MLflow's default store, which in mlflow>=3 raises on the file store
            # (maintenance mode) unless MLFLOW_ALLOW_FILE_STORE is set. setup_mlflow sets
            # that flag and pins the run to file:./mlruns under the session experiment.
            # Idempotent if setup_tracing already ran.
            setup_mlflow(self.experiment or "ema_nlp")
            params = self.pipeline_config.resolved_attributes() if self.pipeline_config else None
            record_answer_run(run_name or "agent_run", answer, params=params, query=query)
        return answer

    def run(self, query: str, **kwargs: Any) -> RegulatoryAnswer:
        return asyncio.run(self.arun(query, **kwargs))


def build_session(
    *,
    agent_name: str = "regulatory",
    retrieval_profile: str | None = None,
    pipeline_profile: str = "native",
    model_name: str = "claude_opus",
    temperature: float = 0.0,
    experiment: str | None = None,
    acronyms: dict[str, str] | None = None,
    enable_tracing: bool = False,
) -> AgentSession:
    """Runtime entry point: open the index, build the retriever + LLM, wire the agent.

    Needs Neo4j + model credentials (runtime; debugged on the GPU host).
    """
    from harness.indexing import build_retriever, load_index_profile, open_index
    from harness.llms import get_llm_for_model

    if enable_tracing:
        from harness.obs import setup_tracing

        setup_tracing(experiment or "ema_nlp")

    profile = load_index_profile(retrieval_profile)
    index = open_index(profile)
    base_retriever = build_retriever(profile, index)
    llm = get_llm_for_model(model_name, temperature_override=temperature)
    pipeline_config = load_pipeline_config(pipeline_profile)
    agent = assemble_agent(
        base_retriever=base_retriever,
        llm=llm,
        agent_name=agent_name,
        pipeline_config=pipeline_config,
        acronyms=acronyms if acronyms is not None else _load_default_acronyms(),
    )
    return AgentSession(agent=agent, pipeline_config=pipeline_config, experiment=experiment)
