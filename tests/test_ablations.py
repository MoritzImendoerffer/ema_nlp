"""
Unit tests for a1_query_expansion (acronym expansion, canonical→acronym,
context guard). The A2/A3/A4 ablations were removed in LIR-012 (they depended
on the deleted harness.retrieve API); only A1 survives, used by the ReAct workflow.
"""

from __future__ import annotations

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


# NOTE: A2/A3/A4 (topic-filter + rerankers) tests were removed in LIR-012 —
# those ablation modules depended on the deleted harness.retrieve API. Only A1
# (query expansion) survives; it is used by the ReAct workflow.
