"""Unit tests for harness.ontology.schema (typed Layer-2 ontology schema)."""

from harness.ontology.schema import OntologySchema, load_ontology_schema


def test_load_ema_ontology_schema():
    schema = load_ontology_schema("ema")
    assert isinstance(schema, OntologySchema)
    assert "Substance" in schema.entities
    assert "Limit" in schema.entities
    assert "HAS_LIMIT" in schema.relations
    assert "JUSTIFIED_BY" in schema.relations


def test_validation_schema_as_triples():
    schema = load_ontology_schema("ema")
    triples = schema.as_triples()
    assert ("Substance", "HAS_LIMIT", "Limit") in triples
    assert all(len(t) == 3 for t in triples)


def test_missing_schema_raises():
    try:
        load_ontology_schema("does_not_exist")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
