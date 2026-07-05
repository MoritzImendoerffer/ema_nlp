"""Unit tests for harness.agents.runner (output coercion + run drivers).

The live LLM call is not exercised; a fake agent returns canned AgentOutput-like
objects so coercion and the run drivers are verified offline.
"""

import asyncio

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from harness.agents.runner import arun_agent, coerce_answer, run_agent
from harness.retrieval import RetrievalPipelineConfig
from harness.schemas import Citation, Claim, RegulatoryAnswer


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


class _FakeRetriever(BaseRetriever):
    """Returns one node with a real score + doc_id, like the live retriever."""

    def _retrieve(self, query_bundle: QueryBundle):
        return [
            NodeWithScore(
                node=TextNode(
                    text="The AI for NDMA is 96 ng/day.",
                    id_="chunk-1",
                    metadata={"source_url": "https://ema.europa.eu/ndma", "doc_id": "d1"},
                ),
                score=0.91,
            )
        ]


class _SearchingAgent:
    """Fake agent that calls ``ema_search`` (so nodes are captured) before answering."""

    def __init__(self, tool, output):
        self._tool = tool
        self._output = output

    async def run(self, user_msg=None, **_):
        self._tool.call(query=user_msg)
        return self._output


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


def test_coerce_from_response_text_with_evidence_citations():
    out = coerce_answer(
        _FakeAgentOutput(response=_FakeChatMsg("hello")), evidence_nodes=[_FakeNode()]
    )
    assert out.answer == "hello"
    assert out.citations[0].source_url == "u"


def test_coerce_from_plain_string():
    assert coerce_answer("just text").answer == "just text"


def test_coerce_rebuilds_citations_from_evidence_nodes():
    # The LLM authored a URL-only citation; evidence nodes carry real provenance.
    structured = RegulatoryAnswer(
        answer="a", citations=[Citation(source_url="https://ema.europa.eu/ndma")]
    )
    nodes = _FakeRetriever()._retrieve(QueryBundle(query_str="x"))
    out = coerce_answer(_FakeAgentOutput(structured_response=structured), evidence_nodes=nodes)
    assert len(out.citations) == 1
    cit = out.citations[0]
    # doc_id / score / quote were the fields the LLM-authored citation left empty.
    assert cit.doc_id == "d1"
    assert cit.score == 0.91
    assert "96 ng/day" in cit.quote


def test_coerce_enriches_claim_level_citations_by_url():
    structured = RegulatoryAnswer(
        answer="a",
        claims=[
            Claim(
                text="AI for NDMA is 96 ng/day",
                citations=[Citation(source_url="https://ema.europa.eu/ndma")],  # url-only
            )
        ],
    )
    nodes = _FakeRetriever()._retrieve(QueryBundle(query_str="x"))
    out = coerce_answer(_FakeAgentOutput(structured_response=structured), evidence_nodes=nodes)
    claim_cit = out.claims[0].citations[0]
    assert claim_cit.doc_id == "d1"
    assert claim_cit.score == 0.91


def test_coerce_without_nodes_preserves_passthrough_identity():
    ans = RegulatoryAnswer(answer="x", citations=[Citation(source_url="u")])
    assert coerce_answer(ans) is ans  # no evidence nodes -> untouched


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
    cfg = RetrievalPipelineConfig(profile="x", query_transform="acronym")
    agent = _FakeAgent(_FakeAgentOutput(response=_FakeChatMsg("z")))
    # stamping is best-effort and no-ops without an active recording span
    out = asyncio.run(arun_agent(agent, "q", pipeline_config=cfg))
    assert out.answer == "z"


def test_arun_agent_captures_search_nodes_into_citations():
    """End-to-end: ema_search runs during the agent turn -> nodes -> real citations."""
    from harness.tools import get_tool

    tool = get_tool("ema_search", retriever=_FakeRetriever())
    agent = _SearchingAgent(
        tool, _FakeAgentOutput(structured_response=RegulatoryAnswer(answer="ok"))
    )
    out = asyncio.run(arun_agent(agent, "ndma acceptable intake"))
    assert out.answer == "ok"
    assert out.citations and out.citations[0].doc_id == "d1"
    assert out.citations[0].score == 0.91
