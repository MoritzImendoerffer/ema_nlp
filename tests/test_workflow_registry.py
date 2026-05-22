"""
Tests for harness/workflows/registry.py — get_workflow() and list_workflows().
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.workflows.registry import WORKFLOW_REGISTRY, get_workflow, list_workflows


class TestListWorkflows:
    def test_returns_sorted_list(self):
        names = list_workflows()
        assert names == sorted(names)

    def test_contains_all_nine_strategies(self):
        expected = {
            "simple_rag_zero", "simple_rag_few", "simple_rag_cot",
            "react", "crag", "summarize_rag",
            "crag_summarize", "crag_review", "react_review",
        }
        assert expected == set(list_workflows())

    def test_registry_and_list_agree(self):
        assert set(list_workflows()) == set(WORKFLOW_REGISTRY)


class TestGetWorkflow:
    def test_raises_on_unknown_name(self):
        with pytest.raises(ValueError, match="Unknown workflow"):
            get_workflow("nonexistent_strategy", index=MagicMock(), llm=MagicMock())

    def test_returns_object_with_invoke(self):
        import asyncio
        from typing import ClassVar
        from llama_index.core.embeddings import BaseEmbedding
        from harness.embed import EMBED_DIM, build_index
        from corpus.extractors.html_extractor import _qa_id
        from corpus.models import QARecord
        from llama_index.core.base.llms.types import ChatMessage, ChatResponse, MessageRole
        import tempfile
        from pathlib import Path

        class _FakeEmbed(BaseEmbedding):
            dim: ClassVar[int] = EMBED_DIM
            def _get_query_embedding(self, q):
                import hashlib, random
                h = int(hashlib.md5(q.encode()).hexdigest(), 16)
                rng = random.Random(h)
                raw = [rng.gauss(0, 1) for _ in range(self.dim)]
                norm = sum(x**2 for x in raw)**0.5
                return [x/norm for x in raw]
            def _get_text_embedding(self, t):
                return self._get_query_embedding(t)
            async def _aget_query_embedding(self, q):
                return self._get_query_embedding(q)
            async def _aget_text_embedding(self, t):
                return self._get_text_embedding(t)

        url = "https://ema.europa.eu/test"
        rec = QARecord(
            qa_id=_qa_id(url, "test q"),
            question="test q", answer="test a",
            source_url=url, source_type="html_accordion",
            source_title="T", topic_path="/t",
            cross_refs=[], extraction_confidence="high",
        )
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "c.jsonl"
            corpus.write_text(rec.to_json(), encoding="utf-8")
            index = build_index(corpus_path=corpus, index_dir=Path(tmp)/"idx",
                                embed_model=_FakeEmbed())

        async def achat(messages, **kw):
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content="ok"))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        runner = get_workflow("simple_rag_zero", index=index, llm=mock_llm)
        assert hasattr(runner, "invoke")
        assert hasattr(runner, "ainvoke")

        result = runner.invoke({"question": "test"})
        assert "answer_text" in result
        assert "docs" in result

    def test_all_strategy_names_are_buildable(self):
        """Each registry entry is a callable (builder function)."""
        for name, builder in WORKFLOW_REGISTRY.items():
            assert callable(builder), f"{name} builder is not callable"

    def test_error_message_lists_available(self):
        try:
            get_workflow("bad", index=MagicMock(), llm=MagicMock())
        except ValueError as exc:
            assert "simple_rag_zero" in str(exc)
