"""Typed ontology schema (entities + relations) for the semantic graph layer.

Loaded from ``harness/configs/ontology/<name>.yaml``; consumed later by a
LlamaIndex ``SchemaLLMPathExtractor`` via the (deferred) ``enrich_ontology``
entrypoint. This module makes the schema a validated, loadable artifact rather
than prose — the extraction itself is not run here.

See ``docs/TARGET_ARCHITECTURE.md`` §4.5. Distinct from the flat
``concepts.yaml`` (IDMP concept labels) loaded by ``harness.ontology.load_concepts``.
"""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "configs" / "ontology"


class OntologySchema(BaseModel):
    """Allowed entity labels, relation types, and (subject, relation, object) triples."""

    name: str
    entities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    validation_schema: list[tuple[str, str, str]] = Field(default_factory=list)

    def as_triples(self) -> list[tuple[str, str, str]]:
        """Return the validation schema as a list of (subject, relation, object) tuples."""
        return list(self.validation_schema)


def load_ontology_schema(name: str, *, config_dir: Path | None = None) -> OntologySchema:
    """Load ``harness/configs/ontology/<name>.yaml`` into an ``OntologySchema``."""
    directory = config_dir or CONFIG_DIR
    path = directory / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Ontology schema not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return OntologySchema(
        name=name,
        entities=list(raw.get("entities", [])),
        relations=list(raw.get("relations", [])),
        validation_schema=[tuple(t) for t in raw.get("validation_schema", [])],
    )
