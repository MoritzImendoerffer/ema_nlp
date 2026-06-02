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

    def test_contains_all_strategies(self):
        expected = {
            "simple_rag",
            "react", "crag", "summarize_rag",
            "crag_summarize", "crag_review", "react_review",
        }
        assert expected == set(list_workflows())

    def test_registry_and_list_agree(self):
        assert set(list_workflows()) == set(WORKFLOW_REGISTRY)


class TestGetWorkflow:
    def test_raises_on_unknown_name(self):
        with pytest.raises(ValueError, match="Unknown workflow"):
            get_workflow("nonexistent_strategy", retriever=MagicMock(), llm=MagicMock())

    def test_returns_object_with_invoke(self):
        from llama_index.core.base.llms.types import ChatMessage, ChatResponse, MessageRole
        from llama_index.core.retrievers import BaseRetriever
        from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

        class _FakeRetriever(BaseRetriever):
            def _retrieve(self, query_bundle: QueryBundle):
                return [NodeWithScore(
                    node=TextNode(text="test a", metadata={"source_url": "https://ema.europa.eu/test"}),
                    score=0.9,
                )]

        async def achat(messages, **kw):
            return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content="ok"))

        mock_llm = MagicMock()
        mock_llm.achat = achat

        runner = get_workflow("simple_rag", retriever=_FakeRetriever(), llm=mock_llm)
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
            get_workflow("bad", retriever=MagicMock(), llm=MagicMock())
        except ValueError as exc:
            assert "simple_rag" in str(exc)
