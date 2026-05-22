"""
Tests for harness/chains/ — EMARetriever, LLM factory, LCEL chains, dataset upload, evaluators.

All tests use a tiny in-memory index (3 records) via FakeEmbedModel so they run
offline without an ANTHROPIC_API_KEY or FAISS index on disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document
from llama_index.core.embeddings import BaseEmbedding

from corpus.extractors.html_extractor import _qa_id
from corpus.models import QARecord
from harness.embed import EMBED_DIM, build_index


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
        import hashlib
        h = int(hashlib.md5(query.encode()).hexdigest(), 16)
        import random
        rng = random.Random(h)
        raw = [rng.gauss(0, 1) for _ in range(self.dim)]
        norm = sum(x**2 for x in raw) ** 0.5
        return [x / norm for x in raw]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._get_query_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._get_text_embedding(t) for t in texts]


def _write_corpus(path: Path, records: list[QARecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(rec.to_json() + "\n")


@pytest.fixture()
def tiny_index(tmp_path: Path):
    records = [
        _rec("What is the AI for NDMA?", "The AI for NDMA is 96 ng/day.", "/safety/nitrosamines"),
        _rec("What is the MAA procedure?", "MAA is the Marketing Authorisation Application.", "/authorisation"),
        _rec("What documents are required?", "Quality, safety and efficacy data.", "/authorisation"),
    ]
    corpus_path = tmp_path / "corpus.jsonl"
    _write_corpus(corpus_path, records)
    embed = FakeEmbedModel()
    index = build_index(corpus_path, tmp_path / "index", force=True, embed_model=embed)
    return index, records, embed


# ===========================================================================
# LSMT-002: EMARetriever
# ===========================================================================

class TestEMARetriever:
    def test_import(self):
        from harness.chains.retriever import EMARetriever
        assert EMARetriever is not None

    def test_hybrid_returns_documents(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, _records, embed = tiny_index
        retriever = EMARetriever(index=index, mode="hybrid", k=3)
        docs = retriever.invoke("NDMA acceptable intake")
        assert len(docs) >= 1
        assert all(isinstance(d, Document) for d in docs)

    def test_dense_returns_documents(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, _records, embed = tiny_index
        retriever = EMARetriever(index=index, mode="dense", k=2)
        docs = retriever.invoke("nitrosamine limit", config={"configurable": {"embed_model": embed}})
        assert len(docs) >= 1

    def test_bm25_returns_documents(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, _records, embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=2)
        docs = retriever.invoke("MAA procedure")
        assert len(docs) >= 1

    def test_document_has_qa_id_in_metadata(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        docs = retriever.invoke("authorisation")
        for d in docs:
            assert "qa_id" in d.metadata
            assert "score" in d.metadata

    def test_document_page_content_has_qa_format(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        docs = retriever.invoke("MAA")
        assert any("Q:" in d.page_content and "A:" in d.page_content for d in docs)

    def test_filter_by_topic(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        docs = retriever.invoke("data requirements")
        # Only docs with "nitrosamine" in topic_path should remain
        filtered = retriever.filter_by_topic(docs, "nitrosamine")
        for d in filtered:
            assert "nitrosamine" in d.metadata.get("topic_path", "").lower()

    def test_get_cross_refs_empty_for_no_refs(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=1)
        # None of our test records have cross_refs
        docs = retriever.invoke("NDMA")
        assert len(docs) >= 1
        cross = retriever.get_cross_refs(docs[0].metadata["qa_id"])
        assert isinstance(cross, list)

    def test_k_limits_results(self, tiny_index):
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=1)
        docs = retriever.invoke("any query")
        assert len(docs) <= 1


# ===========================================================================
# LSMT-003: LangChain LLM factory
# ===========================================================================

class TestGetLangchainLlm:
    def test_import(self):
        from harness.chains.llms import get_langchain_llm
        assert get_langchain_llm is not None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"})
    def test_mid_returns_chat_anthropic(self):
        from langchain_anthropic import ChatAnthropic
        from harness.chains.llms import get_langchain_llm
        llm = get_langchain_llm("mid")
        assert isinstance(llm, ChatAnthropic)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"})
    def test_frontier_returns_chat_anthropic(self):
        from langchain_anthropic import ChatAnthropic
        from harness.chains.llms import get_langchain_llm
        llm = get_langchain_llm("frontier")
        assert isinstance(llm, ChatAnthropic)

    @patch.dict(os.environ, {"TOGETHER_API_KEY": "together-fake-key"})
    def test_olmo_returns_chat_openai(self):
        from langchain_openai import ChatOpenAI
        from harness.chains.llms import get_langchain_llm
        llm = get_langchain_llm("olmo")
        assert isinstance(llm, ChatOpenAI)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"})
    def test_model_id_matches_models_yaml(self):
        from harness.chains.llms import get_langchain_llm
        from harness.models import load_tier
        llm = get_langchain_llm("mid")
        cfg = load_tier("mid")
        # ChatAnthropic stores model as .model
        assert llm.model == cfg.model_id  # type: ignore[union-attr]

    def test_missing_api_key_raises_os_error(self):
        from harness.chains.llms import get_langchain_llm
        env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
                get_langchain_llm("mid")


# ===========================================================================
# LSMT-004: LCEL simple RAG chains
# ===========================================================================

class TestBuildRagChain:
    """Tests use a mocked LLM so no API key is required."""

    @pytest.fixture()
    def mock_llm(self):
        from langchain_core.messages import AIMessage
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(content="NDMA AI is 96 ng/day. Source: EMA.")
        # Make it work as LCEL step
        llm.__or__ = lambda self, other: other  # minimal LCEL compat placeholder
        return llm

    def test_build_zero_shot_chain(self, tiny_index, mock_llm):
        from harness.chains.simple_rag import build_rag_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        chain = build_rag_chain("zero_shot", retriever=retriever, llm=mock_llm)
        assert chain is not None

    def test_build_few_shot_chain(self, tiny_index, mock_llm):
        from harness.chains.simple_rag import build_rag_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        chain = build_rag_chain("few_shot", retriever=retriever, llm=mock_llm)
        assert chain is not None

    def test_build_cot_chain(self, tiny_index, mock_llm):
        from harness.chains.simple_rag import build_rag_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        chain = build_rag_chain("cot_self", retriever=retriever, llm=mock_llm)
        assert chain is not None

    def test_unknown_strategy_raises(self, tiny_index, mock_llm):
        from harness.chains.simple_rag import build_rag_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        with pytest.raises(ValueError, match="Unknown strategy"):
            build_rag_chain("bad_strategy", retriever=retriever, llm=mock_llm)

    def test_cot_strips_reasoning_block(self):
        from harness.chains.simple_rag import extract_answer
        raw = "<reasoning>step 1\nstep 2</reasoning>\nAnswer: The limit is 96 ng/day."
        result = extract_answer(raw, "cot_self")
        assert "<reasoning>" not in result
        assert "96 ng/day" in result

    def test_extract_empty_cot_returns_sentinel(self):
        from harness.chains.simple_rag import extract_answer
        raw = "<reasoning>all reasoning, nothing after</reasoning>"
        result = extract_answer(raw, "cot_self")
        assert result == "No answer generated."

    def test_format_docs_empty(self):
        from harness.chains.simple_rag import format_docs
        result = format_docs([])
        assert "No relevant" in result

    def test_format_docs_includes_qa_id(self, tiny_index):
        from langchain_core.documents import Document
        from harness.chains.simple_rag import format_docs
        doc = Document(page_content="Q: test\nA: answer", metadata={"qa_id": "abc123", "score": 0.9})
        result = format_docs([doc])
        assert "abc123" in result
        assert "0.900" in result


# ===========================================================================
# LSMT-005: LangSmith dataset upload (mocked client)
# ===========================================================================

class TestUploadBenchmarkDataset:
    def test_raises_file_not_found(self, tmp_path):
        from harness.langsmith_dataset import upload_benchmark_dataset
        with pytest.raises(FileNotFoundError):
            upload_benchmark_dataset(path=tmp_path / "nonexistent.jsonl")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_if_no_api_key(self, tmp_path):
        from harness.langsmith_dataset import upload_benchmark_dataset
        fake = tmp_path / "bench.jsonl"
        fake.write_text('{"bench_id":"T1-001","question":"q","type":"T1","gold_answer":"a","gold_qa_ids":[],"topic_path":"/t"}\n')
        env = {k: v for k, v in os.environ.items() if k != "LANGSMITH_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(OSError, match="LANGSMITH_API_KEY"):
                upload_benchmark_dataset(path=fake)

    @patch.dict(os.environ, {"LANGSMITH_API_KEY": "ls-fake"})
    def test_creates_dataset_and_returns_id(self, tmp_path):
        from harness.langsmith_dataset import upload_benchmark_dataset
        fake = tmp_path / "bench.jsonl"
        items = [
            {"bench_id": "T1-001", "question": "What is AI for NDMA?", "type": "T1",
             "gold_answer": "96 ng/day", "gold_qa_ids": ["id1"], "topic_path": "/safety"},
            {"bench_id": "T2-001", "question": "What is MAA?", "type": "T2",
             "gold_answer": "Marketing Auth.", "gold_qa_ids": [], "topic_path": "/auth"},
        ]
        with fake.open("w") as fh:
            for item in items:
                fh.write(__import__("json").dumps(item) + "\n")

        mock_client = MagicMock()
        mock_ds = MagicMock()
        mock_ds.id = "test-dataset-uuid-1234"
        mock_ds.name = "ema-benchmark-test"
        mock_client.list_datasets.return_value = []   # no existing dataset
        mock_client.create_dataset.return_value = mock_ds
        mock_client.list_examples.return_value = []

        with patch("harness.langsmith_dataset.Client", return_value=mock_client):
            dataset_id = upload_benchmark_dataset(path=fake, dataset_name="ema-benchmark-test")

        assert dataset_id == "test-dataset-uuid-1234"
        mock_client.create_dataset.assert_called_once()
        assert mock_client.create_example.call_count == 2


# ===========================================================================
# LSMT-006: LangSmith evaluators
# ===========================================================================

class TestEvaluators:
    def _make_run(self, question: str, answer: str, docs=None) -> dict:
        from langchain_core.documents import Document
        return {
            "inputs": {"question": question},
            "outputs": {
                "answer_text": answer,
                "docs": docs or [Document(page_content="Q: test\nA: 96 ng/day", metadata={})],
            },
        }

    def _make_example(self, gold_answer: str) -> dict:
        return {"outputs": {"gold_answer": gold_answer}}

    @patch("harness.judge.Judge.faithfulness")
    def test_faithfulness_evaluator_calls_judge(self, mock_faith):
        from harness.chains.evaluators import faithfulness_evaluator
        from harness.judge import JudgeScore
        mock_faith.return_value = JudgeScore(score=4, reason="well grounded")

        run = self._make_run("What is AI for NDMA?", "96 ng/day")
        example = self._make_example("96 ng/day")
        result = faithfulness_evaluator(run, example)

        assert result["key"] == "faithfulness"
        assert result["score"] == pytest.approx(0.8)
        assert "grounded" in result["comment"]

    @patch("harness.judge.Judge.correctness")
    def test_correctness_evaluator_calls_judge(self, mock_corr):
        from harness.chains.evaluators import correctness_evaluator
        from harness.judge import JudgeScore
        mock_corr.return_value = JudgeScore(score=5, reason="exact match")

        run = self._make_run("What is AI for NDMA?", "96 ng/day")
        example = self._make_example("96 ng/day")
        result = correctness_evaluator(run, example)

        assert result["key"] == "correctness"
        assert result["score"] == pytest.approx(1.0)

    @patch("harness.judge.Judge.faithfulness")
    def test_non_answer_gives_zero_score(self, mock_faith):
        from harness.chains.evaluators import faithfulness_evaluator
        from harness.judge import JudgeScore
        mock_faith.return_value = JudgeScore(score=0, reason="answer_generation_failed")

        run = self._make_run("What is AI for NDMA?", "No answer generated.")
        example = self._make_example("96 ng/day")
        result = faithfulness_evaluator(run, example)
        assert result["score"] == 0.0


# ===========================================================================
# LSMT-008: LangGraph ReAct agent
# ===========================================================================

class TestReActAgent:
    @pytest.fixture()
    def mock_llm_tools(self):
        """Mock LLM that calls format_answer on first invocation."""
        from langchain_core.messages import AIMessage
        call_count = {"n": 0}

        class _FakeLLM:
            def bind_tools(self, tools):
                return self
            def invoke(self, messages, **kw):
                call_count["n"] += 1
                # First call: call format_answer tool
                tc = {
                    "id": "tc1",
                    "name": "format_answer",
                    "args": {"answer_text": "AI for NDMA is 96 ng/day.", "cited_qa_ids": ["id1"]},
                }
                msg = AIMessage(content="", tool_calls=[tc])
                return msg

        return _FakeLLM()

    def test_build_react_agent_returns_wrapper(self, tiny_index, mock_llm_tools):
        from harness.chains.agents.react import build_react_agent
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        agent = build_react_agent(retriever=retriever, llm=mock_llm_tools)
        assert hasattr(agent, "invoke")
        assert hasattr(agent, "ainvoke")

    def test_react_invoke_returns_expected_keys(self, tiny_index, mock_llm_tools):
        from harness.chains.agents.react import build_react_agent
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        agent = build_react_agent(retriever=retriever, llm=mock_llm_tools)
        result = agent.invoke({"question": "What is AI for NDMA?"})
        assert "answer_text" in result
        assert "cited_qa_ids" in result
        assert "trajectory" in result
        assert "docs" in result

    def test_react_extract_final_answer(self, tiny_index, mock_llm_tools):
        from harness.chains.agents.react import build_react_agent
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        agent = build_react_agent(retriever=retriever, llm=mock_llm_tools)
        result = agent.invoke({"question": "What is AI for NDMA?"})
        assert "96 ng/day" in result["answer_text"]
        assert "id1" in result["cited_qa_ids"]

    def test_format_docs_for_agent_empty(self):
        from harness.chains.agents.react import _format_docs_for_agent
        result = _format_docs_for_agent([])
        assert "No results" in result

    def test_format_docs_for_agent_includes_qa_id(self):
        from langchain_core.documents import Document
        from harness.chains.agents.react import _format_docs_for_agent
        doc = Document(page_content="Q: test\nA: 96", metadata={"qa_id": "abc", "score": 0.9})
        result = _format_docs_for_agent([doc])
        assert "abc" in result
        assert "0.900" in result


# ===========================================================================
# LSMT-009: Corrective RAG (CRAG)
# ===========================================================================

def _make_crag_llm(response_fn):
    """Wrap a response function in a RunnableLambda so it works in LCEL chains."""
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import AIMessage

    def _invoke(messages, **kw):
        result = response_fn(messages)
        if isinstance(result, str):
            return AIMessage(content=result)
        return result

    return RunnableLambda(_invoke)


class TestCRAG:
    @pytest.fixture()
    def mock_llm_sufficient(self):
        """LLM that grades documents as sufficient and generates an answer."""
        from langchain_core.messages import AIMessage
        call_count = {"n": 0}

        def _response(messages):
            call_count["n"] += 1
            msg_str = str(messages).lower()
            if "sufficient" in msg_str or "grader" in msg_str:
                return AIMessage(content="sufficient")
            if "rewriter" in msg_str:
                return AIMessage(content="rewritten query")
            return AIMessage(content="The AI for NDMA is 96 ng/day.")

        return _make_crag_llm(_response)

    @pytest.fixture()
    def mock_llm_insufficient_then_sufficient(self):
        """LLM that grades as insufficient once, then sufficient."""
        from langchain_core.messages import AIMessage
        calls = []

        def _response(messages):
            calls.append(messages)
            n = len(calls)
            # 1st call = grade (insufficient)
            # 2nd call = rewrite
            # 3rd call = grade (sufficient)
            # 4th call = generate
            if n == 1:
                return AIMessage(content="insufficient")
            elif n == 2:
                return AIMessage(content="rewritten: NDMA acceptable intake EMA")
            elif n == 3:
                return AIMessage(content="sufficient")
            else:
                return AIMessage(content="The AI for NDMA is 96 ng/day.")

        return _make_crag_llm(_response)

    def test_crag_happy_path(self, tiny_index, mock_llm_sufficient):
        from harness.chains.agents.crag import build_crag
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        crag = build_crag(retriever=retriever, llm=mock_llm_sufficient)
        result = crag.invoke({"question": "What is AI for NDMA?"})
        assert "answer_text" in result
        assert result["correction_cycles"] == 0

    def test_crag_correction_path(self, tiny_index, mock_llm_insufficient_then_sufficient):
        from harness.chains.agents.crag import build_crag
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        crag = build_crag(retriever=retriever, llm=mock_llm_insufficient_then_sufficient)
        result = crag.invoke({"question": "What is AI for NDMA?"})
        assert "answer_text" in result
        assert result["correction_cycles"] >= 1

    def test_crag_max_cycle_guard(self, tiny_index):
        """Always-insufficient LLM should not loop forever."""
        from langchain_core.messages import AIMessage
        from harness.chains.agents.crag import MAX_CYCLES, build_crag
        from harness.chains.retriever import EMARetriever

        always_insufficient = _make_crag_llm(lambda messages: AIMessage(content="insufficient"))
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        crag = build_crag(retriever=retriever, llm=always_insufficient)
        result = crag.invoke({"question": "test"})
        assert result["correction_cycles"] <= MAX_CYCLES
        assert "answer_text" in result

    def test_crag_returns_strategy_label(self, tiny_index, mock_llm_sufficient):
        from harness.chains.agents.crag import build_crag
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        crag = build_crag(retriever=retriever, llm=mock_llm_sufficient)
        result = crag.invoke({"question": "test"})
        assert "crag" in result["prompt_strategy"]


# ===========================================================================
# LSMT-010: Chain registry
# ===========================================================================

class TestChainRegistry:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"})
    def test_list_chains_returns_all_strategies(self):
        from harness.chains.registry import list_chains
        chains = list_chains()
        assert set(chains) == {"simple_rag_zero", "simple_rag_few", "simple_rag_cot", "react", "crag"}

    def test_unknown_chain_raises_value_error(self, tiny_index):
        from harness.chains.registry import get_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        with pytest.raises(ValueError, match="Unknown chain"):
            get_chain("nonexistent", retriever=retriever, llm=MagicMock())

    def test_unknown_error_message_lists_available(self, tiny_index):
        from harness.chains.registry import get_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        try:
            get_chain("bad_name", retriever=retriever, llm=MagicMock())
        except ValueError as exc:
            assert "simple_rag_zero" in str(exc)

    def test_get_chain_simple_rag_zero(self, tiny_index):
        from harness.chains.registry import get_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        chain = get_chain("simple_rag_zero", retriever=retriever, llm=MagicMock())
        assert chain is not None

    def test_get_chain_react(self, tiny_index):
        from harness.chains.registry import get_chain
        from harness.chains.retriever import EMARetriever
        index, _records, _embed = tiny_index
        retriever = EMARetriever(index=index, mode="bm25", k=3)
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        chain = get_chain("react", retriever=retriever, llm=mock_llm)
        assert hasattr(chain, "invoke")
