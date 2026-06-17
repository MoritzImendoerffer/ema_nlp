"""Unit tests for harness.agents (config-driven FunctionAgent assembly).

Constructs a real LlamaIndex FunctionAgent with MockLLM + a fake retriever, so
the config -> tools/prompt/output-schema wiring is verified without API keys or
Neo4j. The agent is not *run* (that needs a real LLM); assembly is asserted.
"""

from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.agents import build_agent, load_agent_config, load_agent_prompt
from harness.schemas import RegulatoryAnswer


class _FakeRetriever(BaseRetriever):
    def __init__(self):
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle):
        return [
            NodeWithScore(
                node=TextNode(text="x", metadata={"source_url": "u", "doc_id": "d"}),
                score=0.5,
            )
        ]


def test_load_regulatory_config():
    cfg = load_agent_config("regulatory")
    assert cfg.tools == ["ema_search", "resolve_substance"]
    assert cfg.output_schema == "RegulatoryAnswer"
    assert cfg.retrieval_profile == "neo4j_hier"
    assert cfg.fewshot.get("source") == "mlflow_rated"


def test_load_agent_prompt():
    prompt = load_agent_prompt("agent_regulatory.md")
    assert "ema_search" in prompt
    assert "Acceptable Intake" in prompt


def test_build_agent_wires_tools_prompt_and_schema():
    agent = build_agent(
        "regulatory",
        llm=MockLLM(),
        retriever=_FakeRetriever(),
        fetcher=lambda _q: {},
    )
    assert {t.metadata.name for t in agent.tools} == {"ema_search", "resolve_substance"}
    assert agent.output_cls is RegulatoryAnswer
    assert "Acceptable Intake" in agent.system_prompt
