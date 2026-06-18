"""Unit tests for harness.ontology.enrich (schema mapping + dry-run plan)."""

from harness.ontology.enrich import enrich_ontology, enrichment_plan, schema_extractor_kwargs
from harness.ontology.schema import load_ontology_schema


def test_schema_extractor_kwargs_maps_schema():
    kw = schema_extractor_kwargs(load_ontology_schema("ema"))
    assert "Substance" in kw["possible_entities"]
    assert "HAS_LIMIT" in kw["possible_relations"]
    assert ["Substance", "HAS_LIMIT", "Limit"] in kw["kg_validation_schema"]
    assert kw["strict"] is True


def test_enrichment_plan():
    plan = enrichment_plan("ema", "nitrosamines")
    assert plan["scope"] == "nitrosamines"
    assert plan["entities"] > 0
    assert plan["relations"] > 0
    assert "nitrosamine" in plan["scope_keywords"]
    assert "extractor_kwargs" in plan


def test_enrich_ontology_dry_run_is_pure():
    plan = enrich_ontology("nitrosamines", dry_run=True)
    assert plan["scope"] == "nitrosamines"
    assert plan["schema"] == "ema"
