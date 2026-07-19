"""Unit tests for the AgentWorkflowAdapter (the invoke/ainvoke runner contract).

Covers the pure RegulatoryAnswer→dict mapping + few-shot prepend offline (fake session);
the live Chainlit selection is verified manually.
"""

import asyncio

from harness.agents.workflow_adapter import AgentWorkflowAdapter
from harness.schemas import Citation, RegulatoryAnswer


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


class _RecordingSession:
    def __init__(self, answer: RegulatoryAnswer) -> None:
        self._answer = answer
        self.last_query: str | None = None

    async def arun(self, query: str, **_):
        self.last_query = query
        return self._answer


def test_adapter_prepends_fewshot_context():
    sess = _RecordingSession(RegulatoryAnswer(answer="ok"))
    asyncio.run(
        AgentWorkflowAdapter(sess).ainvoke(
            {"question": "What is the AI for NDMA?", "few_shot_context": "EXAMPLE BLOCK"}
        )
    )
    assert "EXAMPLE BLOCK" in sess.last_query
    assert "What is the AI for NDMA?" in sess.last_query


def test_adapter_without_fewshot_passes_question_only():
    sess = _RecordingSession(RegulatoryAnswer(answer="ok"))
    asyncio.run(AgentWorkflowAdapter(sess).ainvoke({"question": "Q only"}))
    assert sess.last_query == "Q only"


def test_adapter_result_carries_attribution_and_references():
    """ainvoke joins citations to full captured passages and exposes the
    attribution model (spans + numbered references) for UI/export/SME view."""

    from harness.agents.workflow_adapter import AgentWorkflowAdapter
    from harness.schemas import Citation, Claim, RegulatoryAnswer

    full_passage = "Long background. The Acceptable Intake for NDMA is 96 ng/day per CHMP. More."
    answer = RegulatoryAnswer(
        answer="The Acceptable Intake for NDMA is 96 ng/day.",
        claims=[Claim(text="The Acceptable Intake for NDMA is 96 ng/day.",
                      citations=[Citation(source_url="https://ema.eu/n", chunk_id="chunk-9")])],
        citations=[Citation(source_url="https://ema.eu/n", chunk_id="chunk-9",
                            quote="Acceptable Intake for NDMA is 96 ng/day", score=0.9)],
        confidence=0.9,
    )

    class _Node:
        def __init__(self):
            self.node_id = "chunk-9"
            self.text = full_passage
            self.metadata = {"chunk_id": "chunk-9", "source_url": "https://ema.eu/n"}

    class _NWS:
        node = _Node()
        score = 0.9

    class _Session:
        async def arun(self, msg):
            from harness.tools.search import _NODE_SINK

            sink = _NODE_SINK.get()
            if sink is not None:
                sink.append(_NWS())
            return answer

    result = AgentWorkflowAdapter(_Session()).invoke({"question": "q"})
    att = result["attribution"]
    assert "[1]" in att.marked_text
    assert result["references"][0]["n"] == 1
    assert result["references"][0]["full_text"] == full_passage
    assert result["references"][0]["quote_start"] >= 0  # quote located in the passage


def test_adapter_result_carries_chain_steps():
    from harness.tools.events import record_tool_event

    class _ToolCallingSession:
        """Simulates the agent invoking a retrieval tool mid-run."""

        async def arun(self, query: str, **_):
            record_tool_event(
                tool="ema_search",
                args={"query": query, "source_category": ""},
                notes=[],
                nodes=[],
                output="body",
            )
            return RegulatoryAnswer(answer="ok")

    out = asyncio.run(AgentWorkflowAdapter(_ToolCallingSession()).ainvoke({"question": "q"}))
    assert len(out["chain_steps"]) == 1
    assert out["chain_steps"][0]["tool"] == "ema_search"
    assert out["chain_steps"][0]["seq"] == 1


def test_adapter_chain_steps_empty_when_no_tools_ran():
    out = asyncio.run(
        AgentWorkflowAdapter(_FakeSession(RegulatoryAnswer(answer="ok"))).ainvoke({"question": "q"})
    )
    assert out["chain_steps"] == []
