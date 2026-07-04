"""Unit tests for harness.agents.session (assemble_agent + AgentSession).

assemble_agent is verified with a fake retriever + MockLLM and an empty rerank
list (so no cross-encoder model download). The runtime composition path is
build_recipe (needs Neo4j).
"""

import asyncio

from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.agents import AgentConfig
from harness.agents.session import AgentSession, assemble_agent
from harness.retrieval import RetrievalPipelineConfig
from harness.schemas import RegulatoryAnswer

_CONFIG = AgentConfig(name="regulatory", tools=["ema_search", "resolve_substance"])


class _FakeRetriever(BaseRetriever):
    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        return [NodeWithScore(node=TextNode(text="x", id_="x", metadata={"source_url": "u"}), score=1.0)]


class _FakeAgentOutput:
    def __init__(self, structured_response):
        self.structured_response = structured_response
        self.response = None


class _FakeAgent:
    def __init__(self, output):
        self._output = output

    async def run(self, user_msg=None, **_):
        return self._output


def test_assemble_agent_with_pipeline_config():
    cfg = RetrievalPipelineConfig(profile="native", query_transform="acronym", rerank=[])
    agent = assemble_agent(
        base_retriever=_FakeRetriever(),
        llm=MockLLM(),
        agent_config=_CONFIG,
        pipeline_config=cfg,
        acronyms={"AI": "Acceptable Intake"},
    )
    assert {t.metadata.name for t in agent.tools} == {"ema_search", "resolve_substance"}
    assert agent.output_cls is RegulatoryAnswer


def test_assemble_agent_plain_without_pipeline():
    agent = assemble_agent(base_retriever=_FakeRetriever(), llm=MockLLM(), agent_config=_CONFIG)
    assert {t.metadata.name for t in agent.tools} == {"ema_search", "resolve_substance"}


def test_session_arun_returns_answer():
    session = AgentSession(agent=_FakeAgent(_FakeAgentOutput(RegulatoryAnswer(answer="ok"))))
    out = asyncio.run(session.arun("q"))
    assert out.answer == "ok"


def test_session_run_sync_wrapper():
    session = AgentSession(agent=_FakeAgent(_FakeAgentOutput(RegulatoryAnswer(answer="sync"))))
    assert session.run("q").answer == "sync"


def test_session_arun_record_configures_backend(tmp_path, monkeypatch):
    # record=True must configure an MLflow backend itself and not crash even when
    # setup_tracing was never called (enable_tracing=False). The default backend is a
    # local sqlite store (mlflow.db); setup_mlflow creates it under cwd.
    from harness.obs import mlflow_available

    monkeypatch.chdir(tmp_path)  # sqlite:///mlflow.db resolves under tmp_path
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)  # force the sqlite default
    session = AgentSession(
        agent=_FakeAgent(_FakeAgentOutput(RegulatoryAnswer(answer="rec"))),
        experiment="ema_test",
    )
    out = asyncio.run(session.arun("q", record=True, run_name="unit"))
    assert out.answer == "rec"
    if mlflow_available():
        assert (tmp_path / "mlflow.db").exists()
