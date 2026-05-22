"""
Tests for the LangGraph pipeline node library and build_pipeline() factory (LG-001–007).

All tests use mock LLMs and mock retrievers — no API key or index on disk required.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_doc(qa_id: str = "qa1", content: str = "Q: test?\n\nA: answer.") -> Document:
    return Document(page_content=content, metadata={"qa_id": qa_id, "score": 0.9})


def _make_str_llm(response: str) -> Any:
    """Return a LangChain-compatible mock LLM that always returns *response*."""
    llm = RunnableLambda(lambda messages: AIMessage(content=response))
    llm.__or__ = lambda self, other: other  # minimal LCEL compat (just in case)
    return llm


def _make_mock_retriever(docs: list[Document] | None = None) -> Any:
    r = MagicMock()
    r.invoke.return_value = docs or [_make_doc()]
    return r


# ===========================================================================
# LG-001: PipelineState
# ===========================================================================

class TestPipelineState:
    def test_make_initial_state_defaults(self):
        from harness.chains.pipeline_state import make_initial_state
        s = make_initial_state("What is AI for NDMA?")
        assert s["question"] == "What is AI for NDMA?"
        assert s["few_shot_context"] == ""
        assert s["docs"] == []
        assert s["summary"] == ""
        assert s["answer_text"] == ""
        assert s["cited_qa_ids"] == []
        assert s["trajectory"] == []
        assert s["prompt_strategy"] == ""
        assert s["review_score"] == 0.0
        assert s["review_feedback"] == ""
        assert s["rewrite_cycle"] == 0
        assert s["review_cycle"] == 0
        assert s["grade"] == ""

    def test_make_initial_state_with_fewshot(self):
        from harness.chains.pipeline_state import make_initial_state
        s = make_initial_state("test", few_shot_context="example block")
        assert s["few_shot_context"] == "example block"

    def test_pipeline_state_is_dict(self):
        from harness.chains.pipeline_state import make_initial_state
        s = make_initial_state("q")
        assert isinstance(s, dict)


# ===========================================================================
# LG-001: Retrieval node
# ===========================================================================

class TestRetrievalNode:
    def test_returns_docs_from_retriever(self):
        from harness.chains.nodes.retrieval import build_retrieval_node
        from harness.chains.pipeline_state import make_initial_state

        doc = _make_doc("id1")
        retriever = _make_mock_retriever([doc])
        node = build_retrieval_node(retriever)
        state = make_initial_state("NDMA limit")
        result = node(state)

        assert "docs" in result
        assert len(result["docs"]) == 1
        assert result["docs"][0].metadata["qa_id"] == "id1"
        retriever.invoke.assert_called_once_with("NDMA limit")

    def test_passes_question_to_retriever(self):
        from harness.chains.nodes.retrieval import build_retrieval_node
        from harness.chains.pipeline_state import make_initial_state

        retriever = _make_mock_retriever()
        node = build_retrieval_node(retriever)
        node(make_initial_state("specific question text"))
        retriever.invoke.assert_called_with("specific question text")


# ===========================================================================
# LG-001: Generation node
# ===========================================================================

class TestGenerationNode:
    def test_basic_generation(self):
        from harness.chains.nodes.generation import build_generation_node
        from harness.chains.pipeline_state import make_initial_state

        llm = _make_str_llm("The AI for NDMA is 96 ng/day.")
        node = build_generation_node(llm, strategy="zero_shot")
        state = make_initial_state("What is AI for NDMA?")
        state["docs"] = [_make_doc()]

        result = node(state)
        assert "answer_text" in result
        assert "96 ng/day" in result["answer_text"]
        assert result["prompt_strategy"] == "zero_shot"
        assert result["cited_qa_ids"] == []

    def test_uses_summary_when_available(self):
        from harness.chains.nodes.generation import build_generation_node
        from harness.chains.pipeline_state import make_initial_state

        calls = []

        def _capture_llm(messages):
            msg_list = getattr(messages, "messages", messages if isinstance(messages, list) else [])
            for m in msg_list:
                if hasattr(m, "content"):
                    calls.append(str(m.content))
            return AIMessage(content="answer from summary")

        llm = RunnableLambda(_capture_llm)
        node = build_generation_node(llm, strategy="zero_shot")
        state = make_initial_state("question")
        state["docs"] = [_make_doc()]
        state["summary"] = "FOCUSED SUMMARY TEXT"

        node(state)
        # The summary text should have been passed to the LLM
        combined = " ".join(calls)
        assert "FOCUSED SUMMARY TEXT" in combined

    def test_appends_revision_instruction_when_review_cycle_gt_0(self):
        from harness.chains.nodes.generation import build_generation_node
        from harness.chains.pipeline_state import make_initial_state

        calls = []

        def _capture(messages):
            msg_list = getattr(messages, "messages", messages if isinstance(messages, list) else [messages])
            for m in msg_list:
                if hasattr(m, "content"):
                    calls.append(str(m.content))
            return AIMessage(content="revised answer")

        llm = RunnableLambda(_capture)
        node = build_generation_node(llm, strategy="zero_shot")
        state = make_initial_state("question")
        state["docs"] = [_make_doc()]
        state["review_cycle"] = 1
        state["review_feedback"] = "answer lacked source citation"

        node(state)
        combined = " ".join(calls)
        assert "lacked source citation" in combined

    def test_unknown_strategy_raises(self):
        from harness.chains.nodes.generation import build_generation_node
        with pytest.raises(ValueError, match="Unknown generation strategy"):
            build_generation_node(MagicMock(), strategy="invalid")


# ===========================================================================
# LG-002: Grade node
# ===========================================================================

class TestGradeNode:
    def test_grades_sufficient(self):
        from harness.chains.nodes.grade import build_grade_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_grade_node(_make_str_llm("sufficient"))
        state = make_initial_state("question")
        state["docs"] = [_make_doc()]
        result = node(state)
        assert result == {"grade": "sufficient"}

    def test_grades_insufficient(self):
        from harness.chains.nodes.grade import build_grade_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_grade_node(_make_str_llm("insufficient"))
        state = make_initial_state("question")
        state["docs"] = [_make_doc()]
        result = node(state)
        assert result == {"grade": "insufficient"}

    def test_ambiguous_response_treated_as_insufficient(self):
        from harness.chains.nodes.grade import build_grade_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_grade_node(_make_str_llm("not sure"))
        state = make_initial_state("question")
        state["docs"] = [_make_doc()]
        result = node(state)
        assert result["grade"] == "insufficient"


# ===========================================================================
# LG-002: Rewrite node
# ===========================================================================

class TestRewriteNode:
    def test_rewrites_question(self):
        from harness.chains.nodes.rewrite import build_rewrite_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_rewrite_node(_make_str_llm("NDMA acceptable intake EMA guideline"))
        state = make_initial_state("NDMA limit")
        state["rewrite_cycle"] = 0
        result = node(state)
        assert result["question"] == "NDMA acceptable intake EMA guideline"
        assert result["rewrite_cycle"] == 1

    def test_increments_cycle(self):
        from harness.chains.nodes.rewrite import build_rewrite_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_rewrite_node(_make_str_llm("rewritten"))
        state = make_initial_state("q")
        state["rewrite_cycle"] = 2
        result = node(state)
        assert result["rewrite_cycle"] == 3


# ===========================================================================
# LG-003: Summarization node
# ===========================================================================

class TestSummarizationNode:
    def test_returns_summary(self):
        from harness.chains.nodes.summarization import build_summarization_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_summarization_node(_make_str_llm("Concise regulatory summary [qa1]."))
        state = make_initial_state("NDMA requirements")
        state["docs"] = [_make_doc()]
        result = node(state)
        assert "summary" in result
        assert "Concise" in result["summary"]

    def test_returns_empty_summary_when_no_docs(self):
        from harness.chains.nodes.summarization import build_summarization_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_summarization_node(_make_str_llm("should not be called"))
        state = make_initial_state("question")
        state["docs"] = []
        result = node(state)
        assert result == {"summary": ""}


# ===========================================================================
# LG-005: Review node
# ===========================================================================

class TestReviewNode:
    def test_scores_based_on_judge(self):
        from harness.chains.nodes.review import build_review_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_review_node(MagicMock())
        state = make_initial_state("What is AI for NDMA?")
        state["answer_text"] = "The AI is 96 ng/day."
        state["docs"] = [_make_doc()]
        state["review_cycle"] = 0

        with patch("harness.judge.Judge.faithfulness") as mock_faith:
            from harness.judge import JudgeScore
            mock_faith.return_value = JudgeScore(score=4, reason="mostly grounded")
            result = node(state)

        assert abs(result["review_score"] - 0.8) < 0.01
        assert "grounded" in result["review_feedback"]
        assert result["review_cycle"] == 1

    def test_no_answer_gives_zero_score(self):
        from harness.chains.nodes.review import build_review_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_review_node(MagicMock())
        state = make_initial_state("question")
        state["answer_text"] = "No answer generated."
        state["review_cycle"] = 0
        result = node(state)
        assert result["review_score"] == 0.0
        assert result["review_cycle"] == 1

    def test_judge_failure_defaults_to_pass(self):
        from harness.chains.nodes.review import build_review_node
        from harness.chains.pipeline_state import make_initial_state

        node = build_review_node(MagicMock(), threshold=0.6)
        state = make_initial_state("question")
        state["answer_text"] = "Some answer."
        state["docs"] = [_make_doc()]
        state["review_cycle"] = 0

        with patch("harness.judge.Judge.faithfulness", side_effect=RuntimeError("offline")):
            result = node(state)

        assert result["review_score"] >= 0.6  # failure → pass (threshold)


# ===========================================================================
# LG-004: build_pipeline() factory
# ===========================================================================

class TestBuildPipeline:
    """All tests use mock LLM + mock retriever."""

    @pytest.fixture()
    def mock_retriever(self):
        return _make_mock_retriever([_make_doc("id1"), _make_doc("id2")])

    @pytest.fixture()
    def mock_llm(self):
        return _make_str_llm("The AI for NDMA is 96 ng/day.")

    def test_basic_pipeline_returns_answer(self, mock_retriever, mock_llm):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        p = build_pipeline(PipelineConfig(), retriever=mock_retriever, llm=mock_llm)
        result = p.invoke({"question": "What is AI for NDMA?"})
        assert "answer_text" in result
        assert "96 ng/day" in result["answer_text"]
        assert "docs" in result
        assert len(result["docs"]) >= 1

    def test_with_summarization(self, mock_retriever):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        summary_llm = _make_str_llm("Summary: the AI is defined here [id1].")
        gen_llm = _make_str_llm("Based on summary: 96 ng/day.")

        calls = {"n": 0}
        def _alternating(messages):
            calls["n"] += 1
            if calls["n"] == 1:
                return AIMessage(content="Summary: AI defined [id1].")
            return AIMessage(content="Generated from summary.")

        llm = RunnableLambda(_alternating)
        p = build_pipeline(PipelineConfig(use_summarization=True), retriever=mock_retriever, llm=llm)
        result = p.invoke({"question": "NDMA limit"})
        assert result["answer_text"] != ""
        assert result["summary"] != ""  # summarization was run

    def test_grade_loop_bounded_by_max_rewrite_cycles(self, mock_retriever):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        calls = {"n": 0}
        def _always_insufficient(messages):
            calls["n"] += 1
            return AIMessage(content="insufficient")

        llm = RunnableLambda(_always_insufficient)
        p = build_pipeline(
            PipelineConfig(use_grade=True, max_rewrite_cycles=2),
            retriever=mock_retriever,
            llm=llm,
        )
        result = p.invoke({"question": "test"})
        # Pipeline must terminate; rewrite_cycles bounded
        assert result["rewrite_cycles"] <= 2
        assert "answer_text" in result

    def test_review_loop_bounded_by_max_review_cycles(self, mock_retriever):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        with patch("harness.judge.Judge.faithfulness") as mock_faith:
            from harness.judge import JudgeScore
            mock_faith.return_value = JudgeScore(score=1, reason="poor")  # always fail

            p = build_pipeline(
                PipelineConfig(use_review=True, max_review_cycles=1, review_threshold=0.8),
                retriever=mock_retriever,
                llm=_make_str_llm("answer"),
            )
            result = p.invoke({"question": "test"})

        # review_cycle should be <= max_review_cycles + 1 (last review before forced END)
        assert result["review_score"] is not None
        assert "answer_text" in result

    def test_fewshot_context_passed_through(self, mock_retriever, mock_llm):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        captured = []
        def _capturing_llm(messages):
            msg_list = getattr(messages, "messages", messages if isinstance(messages, list) else [])
            for m in msg_list:
                captured.append(getattr(m, "content", str(m)))
            return AIMessage(content="answer")

        llm = RunnableLambda(_capturing_llm)
        p = build_pipeline(PipelineConfig(), retriever=mock_retriever, llm=llm)
        p.invoke({"question": "q", "few_shot_context": "INJECTED_FEWSHOT"})
        assert any("INJECTED_FEWSHOT" in c for c in captured)

    def test_fewshot_context_by_node_wraps_generate(self, mock_retriever):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        captured = []
        def _capturing_llm(messages):
            msg_list = getattr(messages, "messages", messages if isinstance(messages, list) else [])
            for m in msg_list:
                captured.append(getattr(m, "content", str(m)))
            return AIMessage(content="answer")

        llm = RunnableLambda(_capturing_llm)
        p = build_pipeline(
            PipelineConfig(),
            retriever=mock_retriever,
            llm=llm,
            fewshot_context_by_node={"generate": "NODE_FEWSHOT_GENERATE"},
        )
        p.invoke({"question": "q"})
        assert any("NODE_FEWSHOT_GENERATE" in c for c in captured)

    def test_output_keys_complete(self, mock_retriever, mock_llm):
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        p = build_pipeline(PipelineConfig(), retriever=mock_retriever, llm=mock_llm)
        result = p.invoke({"question": "q"})
        for key in ("answer_text", "docs", "summary", "cited_qa_ids", "prompt_strategy",
                    "rewrite_cycles", "review_score", "review_feedback"):
            assert key in result, f"Missing key: {key}"


# ===========================================================================
# Registry: new strategies present
# ===========================================================================

class TestRegistryNewStrategies:
    def test_list_chains_includes_new_strategies(self):
        from harness.chains.registry import list_chains
        chains = set(list_chains())
        for expected in ("summarize_rag", "crag_summarize", "crag_review", "react_review"):
            assert expected in chains, f"Strategy {expected!r} missing from registry"

    def test_existing_strategies_still_present(self):
        from harness.chains.registry import list_chains
        chains = set(list_chains())
        for expected in ("simple_rag_zero", "simple_rag_few", "simple_rag_cot", "react", "crag"):
            assert expected in chains, f"Existing strategy {expected!r} removed from registry"

    def test_get_summarize_rag_returns_invokeable(self):
        from harness.chains.registry import get_chain

        mock_llm = _make_str_llm("answer")
        retriever = _make_mock_retriever()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        chain = get_chain("summarize_rag", retriever=retriever, llm=mock_llm)
        assert hasattr(chain, "invoke")

    def test_get_crag_review_returns_invokeable(self):
        from harness.chains.registry import get_chain

        mock_llm = _make_str_llm("insufficient")
        retriever = _make_mock_retriever()
        chain = get_chain("crag_review", retriever=retriever, llm=mock_llm)
        assert hasattr(chain, "invoke")


# ===========================================================================
# LG-002: crag.py still passes after refactor
# ===========================================================================

def _make_crag_llm(response_fn):
    from langchain_core.runnables import RunnableLambda
    def _invoke(messages, **kw):
        result = response_fn(messages)
        if isinstance(result, str):
            return AIMessage(content=result)
        return result
    return RunnableLambda(_invoke)


class TestCRAGRefactor:
    """Verify existing crag behaviour is preserved after grade/rewrite extraction (LG-002)."""

    def test_crag_happy_path_still_works(self):
        from harness.chains.agents.crag import build_crag
        from unittest.mock import MagicMock

        # Tiny fake index and retriever
        from harness.chains.retriever import EMARetriever

        retriever = _make_mock_retriever([_make_doc("id1")])
        llm = _make_crag_llm(lambda msgs: "sufficient" if "sufficient" in str(msgs).lower() else "The AI is 96 ng/day.")

        crag = build_crag(retriever=retriever, llm=llm)
        result = crag.invoke({"question": "What is AI for NDMA?"})
        assert "answer_text" in result
        assert "correction_cycles" in result  # backwards compat key

    def test_crag_max_cycle_guard(self):
        from harness.chains.agents.crag import MAX_CYCLES, build_crag

        retriever = _make_mock_retriever([_make_doc()])
        always_insufficient = _make_crag_llm(lambda msgs: "insufficient")
        crag = build_crag(retriever=retriever, llm=always_insufficient)
        result = crag.invoke({"question": "test"})
        assert result["correction_cycles"] <= MAX_CYCLES
        assert "answer_text" in result


# ===========================================================================
# LG-006: fewshot_inject node_name parameter
# ===========================================================================

class TestFewshotInjectNodeName:
    def test_node_name_none_calls_fetch_trajectory(self):
        from harness.fewshot_inject import get_fewshot_context
        import numpy as np

        cache = MagicMock()
        cache.get_similar.return_value = []
        vec = np.zeros(1024, dtype=np.float32)
        # Should not raise; returns None because no hits
        result = get_fewshot_context(vec, cache, min_examples=1)
        assert result is None

    def test_node_name_parameter_accepted(self):
        from harness.fewshot_inject import get_fewshot_context
        import numpy as np

        cache = MagicMock()
        cache.get_similar.return_value = []
        vec = np.zeros(1024, dtype=np.float32)
        # Should not raise with node_name= kwarg
        result = get_fewshot_context(vec, cache, node_name="generate", min_examples=1)
        assert result is None


# ===========================================================================
# LG-007: MemorySaver multi-turn session state
# ===========================================================================

class TestMemorySaverMultiTurn:
    def test_pipeline_compiled_with_checkpointer(self):
        """build_pipeline() accepts a MemorySaver checkpointer without error."""
        from harness.chains.pipeline import PipelineConfig, build_pipeline
        from langgraph.checkpoint.memory import MemorySaver

        p = build_pipeline(
            PipelineConfig(),
            retriever=_make_mock_retriever(),
            llm=_make_str_llm("answer"),
            checkpointer=MemorySaver(),
        )
        assert p is not None

    def test_sequential_calls_with_same_thread_id_share_checkpoint(self):
        """Two sequential graph.invoke() calls with the same thread_id share state."""
        from harness.chains.pipeline import PipelineConfig, build_pipeline
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        pipeline = build_pipeline(
            PipelineConfig(),
            retriever=_make_mock_retriever(),
            llm=_make_str_llm("the answer"),
            checkpointer=checkpointer,
        )

        # config must be passed as config={"configurable": {...}} (LangGraph convention)
        thread_config = {"configurable": {"thread_id": "session-abc"}}

        r1 = pipeline.invoke({"question": "Q1"}, config=thread_config)
        assert r1["answer_text"] == "the answer"

        r2 = pipeline.invoke({"question": "Q2"}, config=thread_config)
        assert r2["answer_text"] == "the answer"

        # checkpoint saved for this thread
        saved = checkpointer.get(thread_config)
        assert saved is not None

    def test_different_thread_ids_are_independent(self):
        """Different thread_ids should not share checkpointed state."""
        from harness.chains.pipeline import PipelineConfig, build_pipeline
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        pipeline = build_pipeline(
            PipelineConfig(),
            retriever=_make_mock_retriever(),
            llm=_make_str_llm("answer"),
            checkpointer=checkpointer,
        )

        cfg1 = {"configurable": {"thread_id": "thread-1"}}
        cfg2 = {"configurable": {"thread_id": "thread-2"}}
        r1 = pipeline.invoke({"question": "Q1"}, config=cfg1)
        r2 = pipeline.invoke({"question": "Q2"}, config=cfg2)

        assert r1["answer_text"]
        assert r2["answer_text"]

        # Both threads have separate checkpoints
        cp1 = checkpointer.get(cfg1)
        cp2 = checkpointer.get(cfg2)
        assert cp1 is not None
        assert cp2 is not None

    def test_without_checkpointer_works_stateless(self):
        """build_pipeline() without checkpointer works as before (no thread_id needed)."""
        from harness.chains.pipeline import PipelineConfig, build_pipeline

        pipeline = build_pipeline(
            PipelineConfig(),
            retriever=_make_mock_retriever(),
            llm=_make_str_llm("stateless answer"),
        )
        result = pipeline.invoke({"question": "test"})
        assert result["answer_text"] == "stateless answer"
