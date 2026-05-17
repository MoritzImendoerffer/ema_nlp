"""IDMP ontology helpers — concept loading for A2 topic filter."""

from __future__ import annotations

from pathlib import Path

import yaml

_CONCEPTS_PATH = Path(__file__).parent / "concepts.yaml"


def load_concepts(path: Path = _CONCEPTS_PATH) -> list[str]:
    """Return the list of IDMP concept label strings from concepts.yaml."""
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("concepts", [])
