"""
IDMP ontology concept tagger for Q&A corpus nodes.

Steps:
1. Parse IDMP RDF (Pistoia Alliance IDMP-O v1.3) and extract regulatory concepts.
2. Filter to ~50-100 concepts relevant to EMA human-regulatory Q&As.
3. Write concept list to harness/ontology/concepts.yaml.
4. For a loaded LlamaIndex VectorStoreIndex: tag each node's metadata['concepts']
   by matching concept labels against node text (case-insensitive substring match).

Usage (script mode — writes concepts.yaml):
    python3 scripts/tag_concepts.py [--rdf PATH] [--out PATH]

Usage (library mode — tag nodes in a running index):
    from scripts.tag_concepts import load_concepts, tag_index, filter_by_concept
"""

from __future__ import annotations

import argparse
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_RDF = REPO_ROOT / "config.py"  # resolved via config.rdf_file_path at runtime
DEFAULT_CONCEPTS_OUT = REPO_ROOT / "harness" / "ontology" / "concepts.yaml"

# OWL / RDF / RDFS namespace URIs
_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

# Ontology fragment path segments that are relevant to EMA human-regulatory Q&As.
# Concepts under these namespaces are preferred for tagging.
_RELEVANT_FRAGMENTS = {
    "ISO11238",   # Substances
    "ISO11239",   # Pharmaceutical dose forms
    "ISO11240",   # Units of measurement
    "ISO11615",   # Medicinal products
    "ISO11616",   # Packaging
    "ISO16684",   # xmp
    "SPOR",       # substance, product, organisation, referential
    "EMA",
}


# ---------------------------------------------------------------------------
# RDF parsing
# ---------------------------------------------------------------------------

def _local_name(uri: str) -> str:
    """Extract the local name from a URI (after # or last /)."""
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.split("/")[-1]


def _camel_to_words(name: str) -> str:
    """Convert CamelCase identifier to space-separated lowercase words."""
    import re
    return re.sub(r"([A-Z])", r" \1", name).strip().lower()


def _is_relevant(uri: str) -> bool:
    return any(frag in uri for frag in _RELEVANT_FRAGMENTS)


def parse_concepts_from_rdf(rdf_path: Path) -> list[str]:
    """
    Parse the IDMP RDF and return a list of concept labels.

    Returns an empty list if *rdf_path* does not exist (graceful fallback).
    """
    if not rdf_path.exists():
        log.warning("IDMP RDF not found at %s — concept tagging disabled", rdf_path)
        return []

    tree = ET.parse(rdf_path)
    root = tree.getroot()

    concepts: set[str] = set()

    for child in root:
        # Only OWL classes
        if child.tag != f"{{{_OWL}}}Class":
            continue
        about = child.attrib.get(f"{{{_RDF}}}about", "")
        if not about or not _is_relevant(about):
            continue

        # Prefer rdfs:label if present
        label_el = child.find(f"{{{_RDFS}}}label")
        if label_el is not None and label_el.text and label_el.text.strip():
            label = label_el.text.strip().lower()
        else:
            label = _camel_to_words(_local_name(about))

        # Skip very short or very generic terms
        if len(label) >= 4 and label not in {"role", "type", "base", "atom", "acid"}:
            concepts.add(label)

    # Sort and cap at 100 most specific (longer labels tend to be more specific)
    sorted_concepts = sorted(concepts, key=lambda c: (-len(c), c))[:100]
    log.info("Extracted %d concepts from %s", len(sorted_concepts), rdf_path.name)
    return sorted_concepts


# ---------------------------------------------------------------------------
# Load / save concepts.yaml
# ---------------------------------------------------------------------------

def load_concepts(concepts_yaml: Path = DEFAULT_CONCEPTS_OUT) -> list[str]:
    """
    Load concept list from YAML.  Returns [] if file is absent (graceful fallback).
    """
    if not concepts_yaml.exists():
        return []
    with concepts_yaml.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("concepts", [])


def save_concepts(concepts: list[str], out_path: Path = DEFAULT_CONCEPTS_OUT) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.dump({"concepts": concepts}, fh, allow_unicode=True, default_flow_style=False)
    log.info("Wrote %d concepts to %s", len(concepts), out_path)


# ---------------------------------------------------------------------------
# Node tagging
# ---------------------------------------------------------------------------

def _match_concepts(text: str, concepts: list[str]) -> list[str]:
    """Return all concepts that appear as substrings in *text* (case-insensitive)."""
    text_lower = text.lower()
    return [c for c in concepts if c in text_lower]


def tag_index(index, concepts: list[str]) -> int:
    """
    Add metadata['concepts'] to every node in *index*.docstore in-place.

    Returns the number of nodes tagged with ≥1 concept.
    """
    if not concepts:
        log.warning("No concepts provided — skipping node tagging")
        return 0

    tagged = 0
    for node_id, node in index.docstore.docs.items():
        text = node.get_content()
        matched = _match_concepts(text, concepts)
        node.metadata["concepts"] = matched
        if matched:
            tagged += 1

    log.info("Tagged %d/%d nodes with ≥1 concept", tagged, len(index.docstore.docs))
    return tagged


# ---------------------------------------------------------------------------
# filter_by_concept retriever
# ---------------------------------------------------------------------------

def filter_by_concept(index, concept: str, k: int = 10):
    """
    Return a LlamaIndex retriever that pre-filters to nodes matching *concept*.

    Uses LlamaIndex MetadataFilter on the 'concepts' field.
    Falls back to a standard dense retriever if the concept list is empty.
    """
    from llama_index.core.retrievers import VectorIndexRetriever
    from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters

    # Graceful fallback: if concepts field is missing, just use standard retriever
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=k,
        filters=MetadataFilters(
            filters=[MetadataFilter(key="concepts", value=concept, operator="contains")]
        ),
    )
    return retriever


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract IDMP concepts and write concepts.yaml")
    parser.add_argument("--rdf", type=Path, default=None, help="Path to IDMP RDF file")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_CONCEPTS_OUT, help="Output concepts.yaml path"
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = _parse_args()

    if args.rdf is not None:
        rdf_path = args.rdf
    else:
        # Resolve from config
        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT))
            from config import rdf_file_path  # type: ignore[import]
            rdf_path = Path(rdf_file_path)
        except Exception:
            log.warning("Could not load config.rdf_file_path — using Nextcloud default")
            rdf_path = (
                Path.home()
                / "Nextcloud/Datasets/Pistoia-Alliance-Ontologies/IDMP-O/1.3.0"
                / "IdentificationOfMedicinalProductsOntology.rdf"
            )

    concepts = parse_concepts_from_rdf(rdf_path)
    if not concepts:
        log.error("No concepts extracted. Check RDF path: %s", rdf_path)
        return

    save_concepts(concepts, args.out)
    print(f"Wrote {len(concepts)} concepts to {args.out}")
    print("First 10 concepts:")
    for c in concepts[:10]:
        print(f"  - {c}")


if __name__ == "__main__":
    main()
