"""Pydantic output/data contracts for the agentic pipeline (aims 2 & 4).

See ``docs/TARGET_ARCHITECTURE.md`` §4.2.
"""

from harness.schemas.answer import (
    Citation,
    Claim,
    RegulatoryAnswer,
    citation_from_node,
    citations_from_nodes,
)
from harness.schemas.substance import Substance

__all__ = [
    "Citation",
    "Claim",
    "RegulatoryAnswer",
    "Substance",
    "citation_from_node",
    "citations_from_nodes",
]
