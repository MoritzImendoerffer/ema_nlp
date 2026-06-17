"""Unit tests for harness.agents.runner (output coercion + run drivers).

The live LLM call is not exercised; a fake agent returns canned AgentOutput-like
objects so coercion and the run drivers are verified offline.
"""

import asyncio

from harness.agents.runner import arun_agent, coerce_answer, run_agent
from harness.retrieval import RetrievalPipelineConfig
from harness.schemas import RegulatoryAnswer


class _FakeChatMsg:
    def __init__(self, content):
        self.content = content


class _FakeAgentOutput:
    def __init__(self, *, structured_response=None, response=None):
        self.structured_response = structured_response
        self.response = response


class _FakeAgent:
    def __init__(self, output):
        self._output = output
        self.last_user_msg = None

    async def run(self, user_msg=None, **_):
        self.last_user_msg = user_msg
        return self._output


class _FakeNode:
    def __init__(self):
        self.text = "evidence"
        self.metadata = {"source_url": "u", "doc_id": "d"}


# --- coerce_answer ----------------------------------------------------------


def test_coerce_passthrough_regulatory_answer():
    ans = RegulatoryAnswer(answer="x")
    assert coerce_answer(ans) is ans


def test_coerce_from_structured_model():
    ans = RegulatoryAnswer(answer="from-structured")
    out = coerce_answer(_FakeAgentOutput(structured_response=ans))
    assert out.answer == "from-structured"


def test_coerce_from_structured_dict():
    out = coerce_answer(_FakeAgentOutput(structured_response={"answer": "d", "confidence": 0.5}))
    assert out.answer == "d"
    assert out.confidence == 0.5


def test_coerce_from_response_text_with_fallback_citations():
    out = coerce_answer(
        _FakeAgentOutput(response=_FakeChatMsg("hello")), fallback_nodes=[_FakeNode()]
    )
    assert out.answer == "hello"
    assert out.citations[0].source_url == "u"


def test_coerce_from_plain_string():
    assert coerce_answer("just text").answer == "just text"


def test_coerce_malformed_structured_falls_back_to_text():
    out = coerce_answer(
        _FakeAgentOutput(structured_response={"not": "valid"}, response=_FakeChatMsg("fallback"))
    )
    assert out.answer == "fallback"


# --- run drivers ------------------------------------------------------------


def test_arun_agent_returns_structured_answer_and_passes_user_msg():
    agent = _FakeAgent(_FakeAgentOutput(structured_response=RegulatoryAnswer(answer="ok")))
    out = asyncio.run(arun_agent(agent, "my question"))
    assert out.answer == "ok"
    assert agent.last_user_msg == "my question"


def test_run_agent_sync_wrapper():
    agent = _FakeAgent(_FakeAgentOutput(response=_FakeChatMsg("sync ok")))
    out = run_agent(agent, "q")
    assert out.answer == "sync ok"


def test_arun_agent_stamps_config_without_recording_span():
    cfg = RetrievalPipelineConfig(profile="x", graph_mode="links")
    agent = _FakeAgent(_FakeAgentOutput(response=_FakeChatMsg("z")))
    # stamping is best-effort and no-ops without an active recording span
    out = asyncio.run(arun_agent(agent, "q", pipeline_config=cfg))
    assert out.answer == "z"
