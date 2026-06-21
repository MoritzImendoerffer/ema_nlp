"""Unit tests for the agent-as-workflow adapter (T6 — app.py wiring).

Covers the pure mapping + registry registration offline (fake session / MockLLM); the
live Chainlit selection is verified manually.
"""

import asyncio

from harness.agents.workflow_adapter import AgentWorkflowAdapter, build_agent_workflow
from harness.schemas import Citation, RegulatoryAnswer
from harness.workflows.registry import WORKFLOW_REGISTRY, get_workflow, list_workflows


class _FakeSession:
    def __init__(self, answer: RegulatoryAnswer) -> None:
        self._answer = answer

    async def arun(self, query: str, **_):  # matches AgentSession.arun
        return self._answer


def test_adapter_maps_regulatory_answer_to_runner_dict():
    ans = RegulatoryAnswer(
        answer="The AI for NDMA is 96 ng/day.",
        citations=[Citation(source_url="https://ema.test/x", quote="AI is 96 ng/day")],
    )
    out = asyncio.run(AgentWorkflowAdapter(_FakeSession(ans)).ainvoke({"question": "q"}))
    assert out["answer_text"] == "The AI for NDMA is 96 ng/day."
    assert len(out["docs"]) == 1
    assert out["docs"][0].metadata["source_url"] == "https://ema.test/x"
    assert out["docs"][0].text == "AI is 96 ng/day"
    assert out["answer"] is ans  # structured answer preserved


def test_agent_is_registered_as_a_workflow_strategy():
    assert "agent" in list_workflows()
    assert "agent" in WORKFLOW_REGISTRY


def test_get_workflow_agent_builds_adapter():
    from llama_index.core.llms import MockLLM
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

    class _FakeRetriever(BaseRetriever):
        def _retrieve(self, query_bundle: QueryBundle):
            return [NodeWithScore(node=TextNode(text="x", id_="x"), score=1.0)]

    runner = get_workflow("agent", retriever=_FakeRetriever(), llm=MockLLM(), prompt_strategy="zero_shot")
    assert isinstance(runner, AgentWorkflowAdapter)
    assert hasattr(runner, "ainvoke") and hasattr(runner, "invoke")


def test_build_agent_workflow_ignores_extra_kwargs():
    from llama_index.core.llms import MockLLM
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

    class _FakeRetriever(BaseRetriever):
        def _retrieve(self, query_bundle: QueryBundle):
            return [NodeWithScore(node=TextNode(text="x", id_="x"), score=1.0)]

    # get_workflow forwards prompt_strategy; the agent builder must tolerate it
    runner = build_agent_workflow(_FakeRetriever(), MockLLM(), prompt_strategy="cot_self")
    assert isinstance(runner, AgentWorkflowAdapter)
