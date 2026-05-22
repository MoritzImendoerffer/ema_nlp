"""
Unit tests for Ablation A components:
  - a1_query_expansion: acronym expansion, canonical→acronym, context guard
  - a2_topic_filter: topic prediction, keyword post-filter
  - a3_reranker / a4_reranker: mock-based payload verification
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ── A1 — Query expansion ──────────────────────────────────────────────────────

class TestA1QueryExpansion:
    def setup_method(self):
        from harness.ablations.a1_query_expansion import QueryExpander
        self.expander = QueryExpander()

    def test_acronym_expands_to_canonical_in_impurity_context(self):
        q = "What is the AI for nitrosamines?"
        result = self.expander.expand(q)
        assert "Acceptable Intake" in result
        assert "AI" in result

    def test_canonical_expands_to_acronym(self):
        q = "What is the Acceptable Intake for nitrosamines?"
        result = self.expander.expand(q)
        assert "AI" in result
        assert "Acceptable Intake" in result

    def test_no_double_expansion(self):
        q = "What is the AI (Acceptable Intake) for nitrosamines?"
        result = self.expander.expand(q)
        assert result.count("Acceptable Intake") == 1

    def test_mah_expands(self):
        q = "What are the obligations of the MAH?"
        result = self.expander.expand(q)
        assert "Marketing Authorisation Holder" in result

    def test_non_impurity_ai_not_expanded(self):
        # "AI" without impurity context should not expand to "Acceptable Intake"
        q = "How does AI compare to traditional methods?"
        result = self.expander.expand(q)
        # No impurity context keywords present — should not expand
        assert "Acceptable Intake" not in result

    def test_ttc_expands(self):
        q = "What is the TTC threshold for genotoxic impurities?"
        result = self.expander.expand(q)
        assert "Threshold of Toxicological Concern" in result

    def test_no_change_when_no_acronyms(self):
        q = "How should I file a variation application?"
        result = self.expander.expand(q)
        # Should not crash; may or may not add acronyms
        assert isinstance(result, str)


# ── A1 — custom dict path ─────────────────────────────────────────────────────

def test_expand_query_function(tmp_path):
    """expand_query convenience function works with a minimal custom dict."""
    from harness.ablations.a1_query_expansion import expand_query

    custom_dict = {
        "acronyms": [
            {
                "acronym": "XYZ",
                "canonical": "Xylophone Yield Zone",
                "synonyms": [],
            }
        ]
    }
    dict_path = tmp_path / "test_dict.yaml"
    dict_path.write_text(yaml.dump(custom_dict))

    result = expand_query("What is the XYZ limit?", dict_path)
    assert "Xylophone Yield Zone" in result


# ── A2 — Topic filter ─────────────────────────────────────────────────────────

class TestA2TopicFilter:
    def _make_results(self, topic_paths: list[str]) -> list:
        """Build fake RetrievalResult list with given topic_paths."""
        return [
            (f"qa_{i}", float(i), {"topic_path": tp, "source_url": ""})
            for i, tp in enumerate(topic_paths)
        ]

    def test_filter_keeps_matching_nodes(self):
        from harness.ablations.a2_topic_filter import filter_by_topic_keyword

        results = self._make_results([
            "nitrosamines/questions-answers",
            "manufacturing/gmp",
            "nitrosamines/ndma",
        ])
        filtered = filter_by_topic_keyword(results, "What is the AI for nitrosamines?", min_results=1)
        assert len(filtered) == 2
        assert all("nitrosamine" in r[2]["topic_path"] for r in filtered)

    def test_fallback_when_no_matches(self):
        from harness.ablations.a2_topic_filter import filter_by_topic_keyword

        results = self._make_results([
            "manufacturing/gmp",
            "quality/specifications",
        ])
        # Query about nitrosamines but no nodes match → fallback to all results
        filtered = filter_by_topic_keyword(
            results, "What is the AI for nitrosamines?", min_results=3
        )
        assert len(filtered) == 2  # original list returned unchanged

    def test_no_topic_predicted_returns_original(self):
        from harness.ablations.a2_topic_filter import filter_by_topic_keyword

        results = self._make_results(["topic-a", "topic-b", "topic-c"])
        filtered = filter_by_topic_keyword(results, "How do I submit a cover letter?")
        assert filtered == results


# ── A3 — SME reranker (mocked) ────────────────────────────────────────────────

def _make_fake_llm(score_sequence: list[str]) -> MagicMock:
    """LlamaIndex LLM mock that returns scores from the sequence on each .chat() call."""
    from llama_index.core.base.llms.types import ChatMessage, ChatResponse, MessageRole

    llm = MagicMock()
    seq = list(score_sequence)

    def chat(messages, **kw):
        text = seq.pop(0) if seq else "0"
        return ChatResponse(message=ChatMessage(role=MessageRole.ASSISTANT, content=text))

    llm.chat.side_effect = chat
    return llm


class TestA3Reranker:
    def _make_results(self) -> list:
        return [
            ("qa_0", 0.9, {"topic_path": "nitrosamines"}),
            ("qa_1", 0.8, {"topic_path": "manufacturing"}),
            ("qa_2", 0.7, {"topic_path": "nitrosamines"}),
        ]

    def _make_index(self, texts: dict[str, str]):
        index = MagicMock()
        def get_node(qa_id):
            node = MagicMock()
            node.text = texts.get(qa_id, "Q: test\nA: test")
            return node
        index.docstore.get_node.side_effect = get_node
        return index

    def test_rerank_reorders_by_score(self):
        """Higher LLM score should bubble to top."""
        from harness.ablations.a3_reranker import rerank

        # qa_0→0, qa_1→2, qa_2→1 so qa_1 ends up first
        llm = _make_fake_llm(["0", "2", "1"])
        results = self._make_results()
        index = self._make_index({
            "qa_0": "Q: ndma?\nA: low",
            "qa_1": "Q: nitrosamine limit?\nA: 0.03 mg/day",
            "qa_2": "Q: testing?\nA: hplc",
        })

        reranked = rerank(results, "nitrosamine AI", index, llm=llm, max_chunks=3)
        assert reranked[0][0] == "qa_1"  # score 2 → first
        assert reranked[1][0] == "qa_2"  # score 1 → second
        assert reranked[2][0] == "qa_0"  # score 0 → last

    def test_rerank_appends_unscored_remainder(self):
        """Chunks beyond max_chunks are appended in original order."""
        from harness.ablations.a3_reranker import rerank

        llm = _make_fake_llm(["1", "1"])
        results = self._make_results()  # 3 results
        index = self._make_index({})

        reranked = rerank(results, "test", index, llm=llm, max_chunks=2)
        assert len(reranked) == 3
        assert reranked[-1][0] == "qa_2"  # unscored → appended last


# ── A4 — Generic reranker (mocked) ───────────────────────────────────────────

def test_a4_rerank_same_interface_as_a3():
    from harness.ablations.a4_reranker import rerank

    llm = _make_fake_llm(["2", "2"])
    results = [("qa_0", 0.9, {}), ("qa_1", 0.8, {})]
    index = MagicMock()
    index.docstore.get_node.return_value = MagicMock(text="Q: x\nA: y")

    reranked = rerank(results, "query", index, llm=llm, max_chunks=2)
    assert len(reranked) == 2
    assert llm.chat.call_count == 2
