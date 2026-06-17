"""Pydantic model for a normalized chemical/drug substance.

Returned by the ``resolve_substance`` tool (``harness.tools.substance``). Keeping
it a typed model (not a dict) lets it flow into citations/answers and be validated.
Depends only on ``pydantic``.
"""

from pydantic import BaseModel, Field


class Substance(BaseModel):
    """Canonical identity for a substance (normalization aid for retrieval)."""

    query: str
    name: str = ""  # canonical / IUPAC / first synonym
    cas: str = ""
    atc: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    molecular_weight: float | None = None
    source: str = ""  # provenance, e.g. "pubchem"
    source_url: str = ""
    found: bool = True
