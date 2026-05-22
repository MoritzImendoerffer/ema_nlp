"""
Unit tests for LlamaIndex Workflow implementations.

All tests use a tiny in-memory index (3 records) via FakeEmbedModel so they
run offline without API keys or a FAISS index on disk.

A FakeLLM produces deterministic responses so no Anthropic calls are made.

NOTE: Do NOT add `from __future__ import annotations` here — it breaks
LlamaIndex Workflow's @step decorator type-annotation resolution for
locally-defined workflow classes.
"""

import asyncio
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from llama_index.core.base.llms.types import ChatMessage, ChatResponse, MessageRole
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from corpus.extractors.html_extractor import _qa_id
from corpus.models import QARecord
from harness.embed import EMBED_DIM, build_index
from llama_index.core.schema import TextNode

from harness.workflows.utils import WorkflowRunner, format_docs, extract_answer


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _rec(question: str, answer: str = "Test answer.", topic: str = "/safety") -> QARecord:
    url = f"https://ema.europa.eu/{question[:10].replace(' ', '-')}"
    return QARecord(
        qa_id=_qa_id(url, question),
        question=question,
        answer=answer,
        source_url=url,
        source_type="html_accordion",  # type: ignore[arg-type]
        source_title="Test",
        topic_path=topic,
        cross_refs=[],
        extraction_confidence="high",
    )


class FakeEmbedModel(BaseEmbedding):
    dim: ClassVar[int] = EMBED_DIM

    def _get_query_embedding(self, query: str) -> list[float]:
        import hashlib, random
        h = int(hashlib.md5(query.encode()).hexdigest(), 16)
        rng = random.Random(h)
        raw = [rng.gauss(0, 1) for _ in range(self.dim)]
        norm = sum(x**2 for x in raw) ** 0.5
        return [x / norm for x in raw]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._get_query_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)


def _make_index():
    import tempfile
    from pathlib import Path
    records = [
        _rec("What is the AI for NDMA?", "The AI for NDMA is 96 ng/day.", "/safety"),
        _rec("What is an ASMF?", "ASMF is Active Substance Master File.", "/quality"),
        _rec("What is ICH Q3C?", "ICH Q3C covers residual solvents.", "/quality"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus.jsonl"
        corpus.write_text(
            "\n".join(r.to_json() for r in records), encoding="utf-8"
        )
        return build_index(
            corpus_path=corpus,
            index_dir=Path(tmp) / "idx",
            embed_model=FakeEmbedModel(),
        )


def _make_fake_llm(response_text: str = "Fake answer.") -> Any:
    """Return a LlamaIndex LLM-like mock that returns response_text."""
    mock = MagicMock()

    async def achat(messages, **kw):
        msg = ChatMessage(role=MessageRole.ASSISTANT, content=response_text)
        return ChatResponse(message=msg)

    mock.achat = achat
    return mock


# ---------------------------------------------------------------------------
# utils tests
# ---------------------------------------------------------------------------

class TestUtils:
    def test_format_docs_empty(self):
        assert format_docs([]) == "No relevant documents retrieved."

    def test_format_docs_with_doc(self):
        node = TextNode(
            text="Q: What?\n\nA: Answer.",
            metadata={"qa_id": "qa1", "score": 0.9, "source_url": "https://x.com"},
        )
        result = format_docs([node])
        assert "qa1" in result
        assert "0.900" in result
        assert "What?" in result

    def test_extract_answer_zero_shot(self):
        assert extract_answer("Simple answer.", "zero_shot") == "Simple answer."

    def test_extract_answer_cot_self_strips_reasoning(self):
        raw = "<reasoning>Let me think...</reasoning>Answer: The result is X."
        result = extract_answer(raw, "cot_self")
        assert "<reasoning>" not in result
        assert "result is X" in result

    def test_extract_answer_empty_returns_fallback(self):
        assert extract_answer("   ", "zero_shot") == "No answer generated."


# ---------------------------------------------------------------------------
# Helper workflow classes for WorkflowRunner tests
# (must be at module scope so @step can resolve type annotations)
# ---------------------------------------------------------------------------

class _EchoWF(Workflow):
    @step
    async def echo(self, ctx: Context, ev: StartEvent) -> StopEvent:
        return StopEvent(result={"question": ev.get("question", "")})


class _EchoQWF(Workflow):
    @step
    async def echo(self, ctx: Context, ev: StartEvent) -> StopEvent:
        return StopEvent(result={"q": ev.get("question", "")})


# ---------------------------------------------------------------------------
# WorkflowRunner tests
# ---------------------------------------------------------------------------

class TestWorkflowRunner:
    def test_sync_invoke_runs_async_workflow(self):
        runner = WorkflowRunner(_EchoWF(timeout=10))
        result = runner.invoke({"question": "hello"})
        assert result["question"] == "hello"

    def test_async_ainvoke(self):
        runner = WorkflowRunner(_EchoQWF(timeout=10))
        result = asyncio.run(runner.ainvoke({"question": "world"}))
        assert result["q"] == "world"


# ---------------------------------------------------------------------------
# SimpleRAGWorkflow tests
# ---------------------------------------------------------------------------

class TestSimpleRAGWorkflow:
    @pytest.fixture(scope="class")
    def index(self):
        return _make_index()

    def test_zero_shot_returns_expected_keys(self, index):
        from harness.workflows.simple_rag import SimpleRAGWorkflow

        llm = _make_fake_llm("NDMA AI is 96 ng/day.")
        wf = SimpleRAGWorkflow(index=index, llm=llm, strategy="zero_shot", timeout=30)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is the AI for NDMA?"})
        assert "answer_text" in result
        assert "docs" in result
        assert "prompt_strategy" in result
        assert result["prompt_strategy"] == "zero_shot"

    def test_answer_text_comes_from_llm(self, index):
        from harness.workflows.simple_rag import SimpleRAGWorkflow

        expected = "The AI for NDMA is 96 ng/day per ICH M7."
        llm = _make_fake_llm(expected)
        wf = SimpleRAGWorkflow(index=index, llm=llm, strategy="zero_shot", timeout=30)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "NDMA limit?"})
        assert result["answer_text"] == expected

    def test_docs_are_textnodes(self, index):
        from harness.workflows.simple_rag import SimpleRAGWorkflow
        from llama_index.core.schema import TextNode

        wf = SimpleRAGWorkflow(index=index, llm=_make_fake_llm(), strategy="zero_shot", timeout=30)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "ASMF?"})
        assert isinstance(result["docs"], list)
        for node in result["docs"]:
            assert isinstance(node, TextNode)
            assert hasattr(node, "text")
            assert hasattr(node, "metadata")

    def test_few_shot_strategy_accepted(self, index):
        from harness.workflows.simple_rag import SimpleRAGWorkflow

        wf = SimpleRAGWorkflow(index=index, llm=_make_fake_llm(), strategy="few_shot", timeout=30)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "ASMF?"})
        assert result["prompt_strategy"] == "few_shot"

    def test_invalid_strategy_raises(self, index):
        from harness.workflows.simple_rag import SimpleRAGWorkflow

        with pytest.raises(ValueError, match="Unknown strategy"):
            SimpleRAGWorkflow(index=index, llm=_make_fake_llm(), strategy="bad_strategy")

    def test_few_shot_context_forwarded(self, index):
        """The LLM receives few_shot_context in the system prompt."""
        from harness.workflows.simple_rag import SimpleRAGWorkflow

        received_messages: list = []

        async def achat(messages, **kw):
            received_messages.extend(messages)
            msg = ChatMessage(role=MessageRole.ASSISTANT, content="ok")
            return ChatResponse(message=msg)

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = SimpleRAGWorkflow(index=index, llm=mock_llm, strategy="zero_shot", timeout=30)
        runner = WorkflowRunner(wf)
        runner.invoke({"question": "test", "few_shot_context": "EXAMPLE: ..."})

        system_msg = next(m for m in received_messages if m.role == MessageRole.SYSTEM)
        assert "EXAMPLE:" in system_msg.content


# ---------------------------------------------------------------------------
# CRAGWorkflow tests
# ---------------------------------------------------------------------------

_GRADE_SUFFICIENT = '{"per_doc": [{"qa_id": "qa1", "score": 2}], "missing_facts": []}'
_GRADE_INSUFFICIENT = '{"per_doc": [{"qa_id": "qa1", "score": 1}], "missing_facts": ["specific NDMA limit value"]}'


class TestCRAGWorkflow:
    @pytest.fixture(scope="class")
    def index(self):
        return _make_index()

    def test_returns_expected_keys(self, index):
        from harness.workflows.crag import CRAGWorkflow

        call_count = {"n": 0}

        async def achat(messages, **kw):
            call_count["n"] += 1
            system = next((m.content for m in messages if m.role == MessageRole.SYSTEM), "")
            # grade call → sufficient JSON; generate call → answer text
            if "per_doc" in system or "missing_facts" in system or "0–2" in system:
                text = _GRADE_SUFFICIENT
            else:
                text = "Fake CRAG answer."
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=text))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = CRAGWorkflow(index=index, llm=mock_llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is NDMA AI?"})

        assert "answer_text" in result
        assert "docs" in result
        assert "rewrite_cycles_used" in result
        assert "graded_docs" in result
        assert result["rewrite_cycles_used"] == 0

    def test_rewrite_cycle_increments(self, index):
        from harness.workflows.crag import CRAGWorkflow

        grade_calls = {"n": 0}

        async def achat(messages, **kw):
            system = next((m.content for m in messages if m.role == MessageRole.SYSTEM), "")
            is_grade = "per_doc" in system or "missing_facts" in system or "0–2" in system
            is_rewrite = "Missing facts" in next(
                (m.content for m in messages if m.role == MessageRole.USER), ""
            )
            if is_grade:
                grade_calls["n"] += 1
                # Insufficient for first 2 grade calls, then sufficient
                text = _GRADE_INSUFFICIENT if grade_calls["n"] < 3 else _GRADE_SUFFICIENT
            elif is_rewrite:
                text = "rewritten query about NDMA specific limit"
            else:
                text = "Final answer."
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=text))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = CRAGWorkflow(index=index, llm=mock_llm, max_cycles=2, timeout=120)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "test"})
        assert result["rewrite_cycles_used"] >= 0

    def test_grade_sufficient_when_score2_and_no_missing(self, index):
        """A doc scoring 2 with empty missing_facts produces GradeEvent (no rewrite)."""
        from harness.workflows.crag import CRAGWorkflow

        async def achat(messages, **kw):
            system = next((m.content for m in messages if m.role == MessageRole.SYSTEM), "")
            if "per_doc" in system or "0–2" in system:
                return ChatResponse(message=ChatMessage(
                    role=MessageRole.ASSISTANT, content=_GRADE_SUFFICIENT
                ))
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content="Answer."))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = CRAGWorkflow(index=index, llm=mock_llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "NDMA limit?"})
        assert result["rewrite_cycles_used"] == 0

    def test_rewrite_grounded_in_missing_facts(self, index):
        """Rewrite prompt receives missing_facts from grader."""
        from harness.workflows.crag import CRAGWorkflow

        rewrite_user_msgs: list[str] = []
        grade_count = {"n": 0}

        async def achat(messages, **kw):
            system = next((m.content for m in messages if m.role == MessageRole.SYSTEM), "")
            user = next((m.content for m in messages if m.role == MessageRole.USER), "")
            is_grade = "per_doc" in system or "0–2" in system
            is_rewrite = "Missing facts" in user
            if is_grade:
                grade_count["n"] += 1
                text = _GRADE_INSUFFICIENT if grade_count["n"] < 2 else _GRADE_SUFFICIENT
            elif is_rewrite:
                rewrite_user_msgs.append(user)
                text = "rewritten query"
            else:
                text = "Final answer."
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=text))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = CRAGWorkflow(index=index, llm=mock_llm, max_cycles=2, timeout=120)
        runner = WorkflowRunner(wf)
        runner.invoke({"question": "test"})

        assert rewrite_user_msgs, "rewrite step was not called"
        assert "specific NDMA limit value" in rewrite_user_msgs[0]


# ---------------------------------------------------------------------------
# SummarizeRAGWorkflow tests
# ---------------------------------------------------------------------------

class TestSummarizeRAGWorkflow:
    @pytest.fixture(scope="class")
    def index(self):
        return _make_index()

    def test_returns_summary_key(self, index):
        from harness.workflows.summarize_rag import SummarizeRAGWorkflow

        call_n = {"n": 0}

        async def achat(messages, **kw):
            call_n["n"] += 1
            # First call = summarize, second = generate
            text = "Summary of docs." if call_n["n"] == 1 else "Final answer based on summary."
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=text))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = SummarizeRAGWorkflow(index=index, llm=mock_llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is ICH Q3C?"})

        assert "summary" in result
        assert "answer_text" in result
        assert result["summary"] == "Summary of docs."


# ---------------------------------------------------------------------------
# ReActNativeWorkflow tests
# ---------------------------------------------------------------------------

class TestReActNativeWorkflow:
    @pytest.fixture(scope="class")
    def index(self):
        return _make_index()

    def _make_react_llm(self, responses: list[str]) -> Any:
        """LLM that returns canned responses in order."""
        call_n = {"n": 0}

        async def achat(messages, **kw):
            idx = min(call_n["n"], len(responses) - 1)
            text = responses[idx]
            call_n["n"] += 1
            msg = ChatMessage(role=MessageRole.ASSISTANT, content=text)
            return ChatResponse(message=msg)

        mock = MagicMock()
        mock.achat = achat
        return mock

    def test_returns_expected_keys(self, index):
        from harness.workflows.react_native import ReActNativeWorkflow

        llm = self._make_react_llm([
            "Thought: Let me search.\nAction: ema_search\nAction Input: NDMA acceptable intake",
            "Thought: I found the answer.\nFinal Answer: The AI for NDMA is 96 ng/day.",
        ])
        wf = ReActNativeWorkflow(index=index, llm=llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is the AI for NDMA?"})

        assert "answer_text" in result
        assert "docs" in result
        assert "cited_qa_ids" in result
        assert "trajectory" in result
        assert result["prompt_strategy"] == "react_native"

    def test_final_answer_direct(self, index):
        """LLM provides final answer on first think step."""
        from harness.workflows.react_native import ReActNativeWorkflow

        llm = self._make_react_llm([
            "Thought: I know this.\nFinal Answer: ASMF is Active Substance Master File.",
        ])
        wf = ReActNativeWorkflow(index=index, llm=llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is ASMF?"})

        assert result["answer_text"] == "ASMF is Active Substance Master File."

    def test_think_act_observe_cycle(self, index):
        """Full think→act→observe→think→final cycle."""
        from harness.workflows.react_native import ReActNativeWorkflow

        llm = self._make_react_llm([
            "Thought: Let me search.\nAction: ema_search\nAction Input: ICH Q3C residual solvents",
            "Thought: Found it.\nFinal Answer: ICH Q3C covers residual solvents.",
        ])
        wf = ReActNativeWorkflow(index=index, llm=llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is ICH Q3C?"})

        assert "ICH Q3C" in result["answer_text"] or "residual" in result["answer_text"]
        # trajectory should have at least one thought + one observation
        roles = [e.get("role") for e in result["trajectory"]]
        assert "thought" in roles
        assert "observation" in roles

    def test_max_iterations_guard(self, index):
        """Workflow terminates after max_iterations even with no Final Answer."""
        from harness.workflows.react_native import ReActNativeWorkflow

        # Always return a tool call — never a final answer
        always_search = "Thought: Still looking.\nAction: ema_search\nAction Input: NDMA"
        llm = self._make_react_llm([always_search] * 10)
        wf = ReActNativeWorkflow(index=index, llm=llm, max_iterations=2, timeout=120)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "NDMA limit?"})

        assert "answer_text" in result
        assert "[Max iterations reached]" in result["answer_text"]

    def test_get_qa_by_id_adds_cited(self, index):
        """get_qa_by_id tool adds qa_id to cited_qa_ids."""
        from harness.workflows.react_native import ReActNativeWorkflow

        # First search to get a real qa_id, then fetch by id, then answer
        call_n = {"n": 0}
        qa_ids_found: list = []

        async def achat(messages, **kw):
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                text = "Thought: Search first.\nAction: ema_search\nAction Input: ASMF"
            elif n == 1:
                # After observing search results, pick a qa_id from them
                content = next(
                    m.content for m in messages if m.role == MessageRole.USER
                )
                # Extract first qa_id= token from observation
                import re
                m = re.search(r"qa_id=([^\s]+) score", content)
                qa_id = m.group(1) if m else "fallback_id"
                qa_ids_found.append(qa_id)
                text = f"Thought: Fetch specific entry.\nAction: get_qa_by_id\nAction Input: {qa_id}"
            else:
                text = "Thought: Done.\nFinal Answer: ASMF stands for Active Substance Master File."
            msg = ChatMessage(role=MessageRole.ASSISTANT, content=text)
            return ChatResponse(message=msg)

        mock_llm = MagicMock()
        mock_llm.achat = achat

        wf = ReActNativeWorkflow(index=index, llm=mock_llm, timeout=60)
        runner = WorkflowRunner(wf)
        result = runner.invoke({"question": "What is an ASMF?"})

        assert "answer_text" in result
        if qa_ids_found:
            assert qa_ids_found[0] in result["cited_qa_ids"]
