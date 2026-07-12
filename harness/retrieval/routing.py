"""Query→category routing — a config-driven topic table, no topics in code.

A *routing table* (``harness/configs/routing/<name>.yaml``, shadowable via
``$EMA_CONFIG_DIR/routing/``) maps query signals (keyword/phrase matches) to a
source-category prior. The router itself is fully generic: rules, keywords,
categories, and modes all come from the YAML; the code only implements ordered
first-match-wins matching over the category vocabulary in
:mod:`harness.retrieval.doc_categories`.

A matched rule yields a :class:`RouteDecision` with one of two modes:

  - ``prefer`` (default, soft): retrieved nodes are reordered so the routed
    categories come first — nothing is excluded.
  - ``filter`` (hard): retrieval is restricted to the routed categories (with an
    automatic unfiltered retry in ``ema_search`` if that yields nothing).

Precedence is decided by the consumer (``ema_search``): an explicit
``source_category`` from the agent always wins over the router; the router is
the *default* for queries where the agent expressed no preference.

Pure and offline-testable: no LLM, no store. See ``docs/RETRIEVAL.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.retrieval.doc_categories import CATEGORIES

log = logging.getLogger(__name__)

MODES = ("prefer", "filter")


@dataclass(frozen=True)
class RoutingRule:
    """One ordered rule: if any keyword matches the query, apply the prior."""

    name: str
    keywords: tuple[str, ...]
    categories: tuple[str, ...]
    mode: str = "prefer"


@dataclass(frozen=True)
class RouteDecision:
    """The prior a matched rule yields (stamped into the tool output/trace)."""

    rule: str
    categories: tuple[str, ...]
    mode: str


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    # Word-boundary-ish match that also works for multi-word phrases and
    # hyphenated terms ("residual solvent", "non-clinical"): the phrase must not
    # be embedded inside a longer word.
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)", re.IGNORECASE)


class QueryRouter:
    """Ordered first-match-wins keyword router over a list of rules."""

    def __init__(self, rules: list[RoutingRule], *, name: str = "custom"):
        self.name = name
        self.rules = list(rules)
        self._patterns: list[list[re.Pattern[str]]] = [
            [_keyword_pattern(kw) for kw in rule.keywords] for rule in self.rules
        ]

    def route(self, query: str) -> RouteDecision | None:
        """First matching rule's decision, or ``None`` (no prior — plain retrieval)."""
        for rule, patterns in zip(self.rules, self._patterns):
            if any(p.search(query) for p in patterns):
                return RouteDecision(rule=rule.name, categories=rule.categories, mode=rule.mode)
        return None


def _rule_from_dict(d: dict, *, index: int) -> RoutingRule:
    name = str(d.get("name") or f"rule_{index}")
    keywords = tuple(str(kw) for kw in (d.get("keywords") or []) if str(kw).strip())
    categories = tuple(str(c) for c in (d.get("categories") or []))
    mode = str(d.get("mode", "prefer"))
    if not keywords:
        raise ValueError(f"routing rule {name!r} has no keywords")
    if not categories:
        raise ValueError(f"routing rule {name!r} has no categories")
    unknown = [c for c in categories if c not in CATEGORIES]
    if unknown:
        raise ValueError(
            f"routing rule {name!r} has unknown categor(ies) {unknown}; "
            f"valid: {list(CATEGORIES)}"
        )
    if mode not in MODES:
        raise ValueError(f"routing rule {name!r} has unknown mode {mode!r}; valid: {list(MODES)}")
    return RoutingRule(name=name, keywords=keywords, categories=categories, mode=mode)


def load_router(name: str = "default", *, config_dir: Path | None = None) -> QueryRouter:
    """Load ``routing/<name>.yaml`` into a :class:`QueryRouter`.

    Same search path as recipes/index profiles: an explicit ``config_dir``
    (tests) wins, else ``$EMA_CONFIG_DIR/routing/`` shadows the built-in
    ``harness/configs/routing/``. Malformed rules are hard config errors — a
    routing table that cannot do what it declares must not load (honest stamping).
    """
    if config_dir is not None:
        path = config_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Routing table not found: {path}")
    else:
        from harness.config_paths import find_config

        found = find_config("routing", f"{name}.yaml")
        if found is None:
            raise FileNotFoundError(
                f"Routing table not found: {name!r} (searched $EMA_CONFIG_DIR/routing "
                "and the built-in routing/)"
            )
        path = found
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = raw.get("routing", raw)
    rules = [
        _rule_from_dict(d or {}, index=i) for i, d in enumerate(section.get("rules") or [])
    ]
    seen: set[str] = set()
    for rule in rules:
        if rule.name in seen:
            raise ValueError(f"routing table {name!r} has duplicate rule name {rule.name!r}")
        seen.add(rule.name)
    log.info("loaded routing table %r: %d rules", name, len(rules))
    return QueryRouter(rules, name=name)
