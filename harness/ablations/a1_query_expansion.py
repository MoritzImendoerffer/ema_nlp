"""
A1 — Acronym-aware query expansion.

Reads ablations/A_evidence_filter/acronym_dict.yaml and expands EMA acronyms
in a query to their canonical forms (and vice versa), making retrieval more
robust against vocabulary mismatch.

Examples:
    "What is the AI for nitrosamines?" →
    "What is the AI (Acceptable Intake) for nitrosamines?"

    "What is the Acceptable Intake for nitrosamines?" →
    "What is the Acceptable Intake (AI) for nitrosamines?"

The expansion is bidirectional and context-aware: for ambiguous acronyms like
"AI", context keywords are checked before expanding.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_DICT_PATH = REPO_ROOT / "ablations" / "A_evidence_filter" / "acronym_dict.yaml"


def load_acronym_dict(dict_path: Path = DEFAULT_DICT_PATH) -> list[dict[str, Any]]:
    with dict_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("acronyms", [])


class QueryExpander:
    """
    Expands acronyms and their canonical forms in a query string.

    Attributes:
        entries: list of acronym dicts from acronym_dict.yaml
    """

    def __init__(self, dict_path: Path = DEFAULT_DICT_PATH) -> None:
        self.entries = load_acronym_dict(dict_path)

    def expand(self, query: str) -> str:
        """Return an expanded version of *query* with acronym/canonical pairs added.

        Each entry is evaluated against the *original* query to decide whether
        expansion is warranted, preventing recursive expansion (e.g. expanding
        "Marketing Authorisation" that was just inserted by the MAH entry).
        """
        original = query
        result = query
        for entry in self.entries:
            result = self._apply_entry(result, entry, original=original)
        return result

    def _context_matches(self, query_lower: str, entry: dict[str, Any]) -> bool:
        """Return True if the query context warrants expanding this entry.

        Context gating only applies to genuinely ambiguous acronyms — those
        whose disambiguation note contains "NOT" (e.g. "AI: NOT artificial
        intelligence"). All other entries are always expanded.
        """
        disambiguation = entry.get("context_disambiguation", [])

        # Only gate if there's a collision warning ("NOT X" in disambiguation)
        is_ambiguous = any("NOT" in d for d in disambiguation)
        if not is_ambiguous:
            return True

        # Ambiguous: require topic path keyword match or synonym match
        topic_paths = entry.get("topic_paths_where_relevant", [])
        for kw in topic_paths:
            if any(part in query_lower for part in kw.replace("-", " ").split()):
                return True

        for syn in entry.get("synonyms", []):
            if syn.lower() in query_lower:
                return True

        return False

    def _apply_entry(self, query: str, entry: dict[str, Any], *, original: str | None = None) -> str:
        """Apply one acronym entry to *query*.

        *original* is the pre-expansion query used to decide whether a match
        was present before any earlier entries ran. This prevents expanding
        tokens that were inserted by a previous entry.
        """
        check_src = original if original is not None else query
        acronym: str = entry["acronym"]
        canonical: str = entry["canonical"]
        synonyms: list[str] = entry.get("synonyms", [])
        check_lower = check_src.lower()
        query_lower = query.lower()

        all_expansions = [canonical] + synonyms

        # 1. Acronym found in original → add canonical if not yet present
        pattern = r"\b" + re.escape(acronym) + r"\b"
        if re.search(pattern, check_src, re.IGNORECASE):
            if not any(exp.lower() in query_lower for exp in all_expansions):
                if self._context_matches(check_lower, entry):
                    query = re.sub(
                        pattern,
                        lambda m: f"{m.group(0)} ({canonical})",
                        query,
                        flags=re.IGNORECASE,
                        count=1,
                    )

        # 2. Canonical (or synonym) found in original → add acronym if not yet present
        query_lower = query.lower()
        if not re.search(pattern, check_src, re.IGNORECASE):
            for form in all_expansions:
                if form.lower() in check_lower:
                    form_pattern = r"\b" + re.escape(form) + r"\b"
                    if re.search(form_pattern, check_src, re.IGNORECASE):
                        _acr = acronym

                        def _sub_fn(m: re.Match, acr: str = _acr) -> str:
                            return f"{m.group(0)} ({acr})"

                        query = re.sub(
                            form_pattern,
                            _sub_fn,
                            query,
                            flags=re.IGNORECASE,
                            count=1,
                        )
                        break

        return query


def expand_query(query: str, dict_path: Path = DEFAULT_DICT_PATH) -> str:
    """Convenience function — expand a single query."""
    return QueryExpander(dict_path).expand(query)
