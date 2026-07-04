"""
Unit tests for harness.retrieval.acronyms (acronym expansion, canonical→acronym,
context guard) and its wiring into the ``acronym`` query transform (F1: the
config-driven default must actually expand, not silently no-op).
"""

from __future__ import annotations

import yaml

# ── Query expansion ───────────────────────────────────────────────────────────

class TestQueryExpansion:
    def setup_method(self):
        from harness.retrieval.acronyms import QueryExpander
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


# ── custom dict path ──────────────────────────────────────────────────────────

def test_expand_query_function(tmp_path):
    """expand_query convenience function works with a minimal custom dict."""
    from harness.retrieval.acronyms import expand_query

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


# ── the config-driven transform default (F1 regression tests) ────────────────

def test_acronym_transform_default_actually_expands():
    """`get_transform("acronym")` with no mapping loads the shipped dictionary
    and produces a second query variant for a known EMA acronym — the exact
    path that was a silent no-op before F1."""
    from harness.retrieval import get_transform

    transform = get_transform("acronym")
    variants = transform("What is the AI for nitrosamines?")
    assert variants[0] == "What is the AI for nitrosamines?"
    assert len(variants) == 2
    assert "Acceptable Intake" in variants[1]


def test_acronym_transform_explicit_mapping_still_works():
    from harness.retrieval import get_transform

    transform = get_transform("acronym", acronyms={"AI": "Acceptable Intake"})
    variants = transform("What is the AI for NDMA?")
    assert len(variants) == 2
    assert "Acceptable Intake" in variants[1]


def test_default_dict_honors_external_config_dir(tmp_path, monkeypatch):
    """$EMA_CONFIG_DIR/retrieval/acronyms.yaml shadows the built-in dictionary."""
    ext = tmp_path / "retrieval"
    ext.mkdir(parents=True)
    (ext / "acronyms.yaml").write_text(
        yaml.dump({"acronyms": [{"acronym": "QQQ", "canonical": "Quality Quorum Quotient"}]})
    )
    monkeypatch.setenv("EMA_CONFIG_DIR", str(tmp_path))

    from harness.retrieval.acronyms import QueryExpander

    expander = QueryExpander()
    assert "Quality Quorum Quotient" in expander.expand("What is the QQQ limit?")
