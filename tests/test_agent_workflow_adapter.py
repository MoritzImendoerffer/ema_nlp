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
