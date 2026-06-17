"""``resolve_substance`` tool — normalize a drug/chemical name via PubChem.

A *normalization* tool (not a content tool): it resolves a name to its canonical
identity (CAS, synonyms, molecular weight) to disambiguate substances and acronyms
*before* searching the EMA corpus. This directly attacks the "AI = Acceptable
Intake, not Artificial Intelligence" failure mode.

The HTTP call lives behind an injectable ``fetcher`` so the parsing logic is pure
and unit-testable offline (and so live calls can be cached for reproducibility).
``parse_pubchem`` handles the raw PUG-REST payload shape.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from llama_index.core.tools import FunctionTool

from harness.schemas import Substance
from harness.tools.registry import register_tool

log = logging.getLogger(__name__)

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_CAS_RE = re.compile(r"\b(\d{2,7}-\d{2}-\d)\b")
_MAX_SYNONYMS = 15

Fetcher = Callable[[str], dict]


def _default_pubchem_fetcher(name: str) -> dict:
    """Fetch raw PubChem property + synonym payloads for ``name`` (live HTTP).

    Not exercised by unit tests (outbound network is restricted in CI). Returns
    ``{"properties": <PropertyTable JSON>, "synonyms": <InformationList JSON>}``.
    """
    quoted = urllib.parse.quote(name)

    def _get(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read().decode())

    props = _get(f"{PUBCHEM_BASE}/compound/name/{quoted}/property/MolecularWeight,IUPACName/JSON")
    synonyms = _get(f"{PUBCHEM_BASE}/compound/name/{quoted}/synonyms/JSON")
    return {"properties": props, "synonyms": synonyms}


def parse_pubchem(query: str, payload: dict) -> Substance:
    """Parse a raw PubChem payload into a ``Substance``."""
    props = (((payload.get("properties") or {}).get("PropertyTable") or {}).get("Properties") or [])
    info = (((payload.get("synonyms") or {}).get("InformationList") or {}).get("Information") or [])
    prop0 = props[0] if props else {}
    synonyms = (info[0].get("Synonym") if info else []) or []

    cas = ""
    for syn in synonyms:
        match = _CAS_RE.search(str(syn))
        if match:
            cas = match.group(1)
            break

    raw_mw = prop0.get("MolecularWeight")
    try:
        mw = float(raw_mw) if raw_mw is not None else None
    except (TypeError, ValueError):
        mw = None

    name = prop0.get("IUPACName") or (synonyms[0] if synonyms else "")
    cid = prop0.get("CID")
    url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else ""

    return Substance(
        query=query,
        name=str(name),
        cas=cas,
        synonyms=[str(s) for s in synonyms[:_MAX_SYNONYMS]],
        molecular_weight=mw,
        source="pubchem",
        source_url=url,
        found=bool(props or synonyms),
    )


def resolve_substance(query: str, *, fetcher: Fetcher | None = None) -> Substance:
    """Resolve ``query`` to a canonical ``Substance`` (``found=False`` on failure)."""
    fetch = fetcher or _default_pubchem_fetcher
    try:
        payload = fetch(query)
    except Exception as exc:  # network/parse errors are non-fatal
        log.warning("resolve_substance failed for %r: %s", query, exc)
        return Substance(query=query, found=False)
    return parse_pubchem(query, payload)


@register_tool("resolve_substance")
def build_resolve_substance_tool(*, fetcher: Fetcher | None = None, **_: Any) -> FunctionTool:
    """Build the ``resolve_substance`` FunctionTool (optionally with a custom fetcher)."""

    def resolve_substance_tool(substance_name: str) -> dict:
        """Resolve a drug/chemical name to canonical identity (CAS, synonyms, MW)."""
        return resolve_substance(substance_name, fetcher=fetcher).model_dump()

    return FunctionTool.from_defaults(
        fn=resolve_substance_tool,
        name="resolve_substance",
        description=(
            "Resolve a drug or chemical substance name to its canonical identity "
            "(CAS number, synonyms, molecular weight) using PubChem. Use this to "
            "disambiguate substances and acronyms before searching the corpus."
        ),
    )
