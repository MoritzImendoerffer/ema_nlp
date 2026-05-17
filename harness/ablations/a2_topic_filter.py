"""
A2 — Topic-path and concept-metadata filtering.

Two modes, selectable via config:

  "keyword"  (default)
      Post-filters retrieved results to those whose topic_path contains at least
      one of the topic keywords predicted from the query. Falls back to the full
      result list if no nodes pass the filter (avoids empty results).

  "concept"
      Uses filter_by_concept() from scripts/tag_concepts.py as the retriever.
      Pre-filters to nodes tagged with a specific IDMP concept string, then runs
      dense similarity search within that subset. Requires the index to have
      concept metadata (populated by scripts/tag_concepts.py).

Topic keyword prediction is heuristic: look for known topic path segments in the
query. This is zero-cost (no LLM call) and handles the most common cases.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from harness.retrieve import RetrievalResult

# ── Topic keyword map ─────────────────────────────────────────────────────────
# Maps topic-path path segments (substrings that appear in corpus topic_path
# values) to sets of query keywords that predict that topic.

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "nitrosamines": [
        "nitrosamine", "n-nitroso", "ndma", "ndea", "nmba", "ccris", "ndipa",
        "nitrosation", "nitrosating agent",
    ],
    "genotoxic-impurities": [
        "genotoxic", "mutagenic", "m7", "icr 3a", "acceptable intake", "ai",
        "threshold of toxicological concern", "ttc",
    ],
    "impurities": [
        "impurit", "degradation product", "residual solvent", "elemental impurit",
        "limit of quantification", "loq", "detection limit", "lod",
        "ich q3", "q3a", "q3b", "q3c", "q3d",
    ],
    "bioequivalence": [
        "bioequivalence", "bioequivalent", "be study", "bioavailability", "bcs",
        "biopharmaceutics classification", "generic", "reference product", "test product",
    ],
    "pharmacovigilance": [
        "pharmacovigilance", "adverse reaction", "adverse event", "psur", "pbrer",
        "pass", "paes", "rmp", "risk management", "safety report", "eudravigilance",
    ],
    "marketing-authorisation": [
        "marketing authorisation", "maa", "mah", "ma application", "cap", "nap",
        "centralised procedure", "mutual recognition", "decentralised procedure",
        "product licence",
    ],
    "manufacturing": [
        "manufactur", "gmp", "good manufacturing practice", "batch release",
        "qualified person", "qp ", "mia", "manufacturing authorisation",
        "in-process control",
    ],
    "quality": [
        "specification", "shelf life", "stability", "drug substance", "drug product",
        "asmf", "cep", "active substance master file", "dossier", "ich q8", "ich q10",
    ],
    "paediatrics": [
        "paediatric", "pediatric", "pip", "pdco", "paediatric investigation plan",
        "children", "neonates", "adolescent",
    ],
    "clinical": [
        "clinical trial", "phase i", "phase ii", "phase iii", "efficacy", "primary endpoint",
        "scientific advice", "protocol assistance",
    ],
    "post-authorisation": [
        "post-authorisation", "post-marketing", "variation", "type i", "type ii",
        "line extension", "annual reassessment",
    ],
}


def _predict_topics(query: str) -> list[str]:
    """Return topic-path segments predicted for this query (zero or more)."""
    query_lower = query.lower()
    matched = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            matched.append(topic)
    return matched


def filter_by_topic_keyword(
    results: list[RetrievalResult],
    query: str,
    *,
    min_results: int = 3,
) -> list[RetrievalResult]:
    """
    Post-filter *results* to those whose topic_path matches predicted topics.

    Falls back to the original list if fewer than *min_results* survive.
    """
    topics = _predict_topics(query)
    if not topics:
        return results

    def _matches(meta: dict) -> bool:
        tp = (meta.get("topic_path") or "").lower()
        return any(t in tp for t in topics)

    filtered = [r for r in results if _matches(r[2])]
    if len(filtered) >= min_results:
        return filtered
    return results  # fallback: no filter applied


def make_concept_retriever(index, query: str, k: int = 10):
    """
    Return a concept-filtered retriever using the first IDMP concept detected
    in *query*, or a standard dense retriever if no concept is detected.

    Requires scripts/tag_concepts.py to have been run on the index.
    """
    sys_path_guard()
    from scripts.tag_concepts import filter_by_concept

    concept = _predict_concept(query)
    if concept:
        return filter_by_concept(index, concept, k=k)
    return index.as_retriever(similarity_top_k=k)


def _predict_concept(query: str) -> str | None:
    """
    Simple concept prediction: match query tokens against known IDMP concept labels.
    Returns the first match or None.
    """
    from harness.ontology import load_concepts

    concepts = load_concepts()
    query_lower = query.lower()
    for concept in concepts:
        # Match 2+ word concepts as substring; 1-word concepts as whole word
        words = concept.split()
        if len(words) >= 2:
            if concept.lower() in query_lower:
                return concept
        else:
            if re.search(r"\b" + re.escape(concept.lower()) + r"\b", query_lower):
                return concept
    return None


def sys_path_guard() -> None:
    """Ensure repo root is on sys.path so scripts/ is importable."""
    import sys

    repo_root = str(Path(__file__).parent.parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


TopicFilterMode = Literal["keyword", "concept"]
