"""Unit tests for harness.retrieval.routing (query→category routing table).

Offline: routers built in-memory or loaded from a tmp config dir; the shipped
default table is validated by loading it for real (it is pure data).
"""

import pytest

from harness.retrieval.routing import QueryRouter, RoutingRule, load_router

# --- matching -----------------------------------------------------------------


def _router() -> QueryRouter:
    return QueryRouter(
        [
            RoutingRule(
                name="impurities",
                keywords=("impurity", "residual solvent"),
                categories=("scientific_guideline", "qa"),
                mode="prefer",
            ),
            RoutingRule(
                name="products",
                keywords=("assessment report",),
                categories=("epar",),
                mode="filter",
            ),
        ]
    )


def test_route_matches_keyword_case_insensitively():
    d = _router().route("What is the Impurity limit for NDMA?")
    assert d is not None
    assert d.rule == "impurities"
    assert d.categories == ("scientific_guideline", "qa")
    assert d.mode == "prefer"


def test_route_matches_multiword_phrase():
    d = _router().route("acceptable residual solvent classes")
    assert d is not None and d.rule == "impurities"


def test_route_requires_word_boundaries():
    # "impurity" embedded in a longer token must not match
    assert _router().route("ximpurityx levels") is None


def test_route_first_match_wins():
    d = _router().route("impurity discussion in the assessment report")
    assert d is not None and d.rule == "impurities"


def test_route_no_match_returns_none():
    assert _router().route("paediatric obligations") is None


# --- loading + validation -------------------------------------------------------


def _write_table(tmp_path, body: str):
    (tmp_path / "custom.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_load_router_from_config_dir(tmp_path):
    d = _write_table(
        tmp_path,
        """
routing:
  rules:
    - name: r1
      keywords: [alpha]
      categories: [qa]
      mode: filter
""",
    )
    router = load_router("custom", config_dir=d)
    decision = router.route("alpha question")
    assert decision is not None and decision.mode == "filter" and decision.categories == ("qa",)


def test_load_router_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_router("nope", config_dir=tmp_path)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("routing:\n  rules:\n    - name: r\n      keywords: []\n      categories: [qa]", "no keywords"),
        ("routing:\n  rules:\n    - name: r\n      keywords: [a]\n      categories: []", "no categories"),
        ("routing:\n  rules:\n    - name: r\n      keywords: [a]\n      categories: [bogus]", "unknown"),
        ("routing:\n  rules:\n    - name: r\n      keywords: [a]\n      categories: [qa]\n      mode: force", "mode"),
    ],
)
def test_load_router_rejects_malformed_rules(tmp_path, body, match):
    d = _write_table(tmp_path, body)
    with pytest.raises(ValueError, match=match):
        load_router("custom", config_dir=d)


def test_load_router_rejects_duplicate_rule_names(tmp_path):
    d = _write_table(
        tmp_path,
        """
routing:
  rules:
    - {name: r, keywords: [a], categories: [qa]}
    - {name: r, keywords: [b], categories: [epar]}
""",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_router("custom", config_dir=d)


def test_shipped_default_table_loads_and_routes():
    router = load_router("default")
    assert router.rules, "shipped routing table must contain rules"
    d = router.route("What is the acceptable intake for a nitrosamine impurity?")
    assert d is not None
    assert "scientific_guideline" in d.categories
