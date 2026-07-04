"""Recipe config — the single user-facing description of a retrieve→generate run.

A *recipe* configures the single engine (a ``FunctionAgent``): the orchestration (system
prompt + toolset + output schema), the retrieval (index profile + optional pipeline +
few-shot policy), the generation (model + temperature), and an optional judge layer.
Recipes are the dropdown's source of truth and the thing stamped on every MLflow trace.

Loaded from ``recipes/<name>.yaml`` via the config search path (built-in
``harness/configs/recipes/`` or an external ``$EMA_CONFIG_DIR/recipes/``), so users
can add/override recipes without editing the source. See ``docs/RECIPES.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from harness.config_paths import find_config

log = logging.getLogger(__name__)


@dataclass
class FewshotPolicy:
    """Runtime few-shot-injection policy (wired in Phase 3)."""

    enabled: bool = False
    source: str = "cache"  # rated query cache
    k: int = 3
    min_rating: float = 4.0
    # Suppress injection below this many qualifying examples. Default 1: inject as
    # soon as a single well-rated similar interaction exists (a hardcoded 3 made
    # injection unreachable for k<3 recipes and untunable, F7).
    min_examples: int = 1

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> FewshotPolicy:
        d = d or {}
        return cls(
            enabled=bool(d.get("enabled", False)),
            source=str(d.get("source", "cache")),
            k=int(d.get("k", 3)),
            min_rating=float(d.get("min_rating", 4.0)),
            min_examples=int(d.get("min_examples", 1)),
        )


@dataclass
class JudgePolicy:
    """Optional post-generation judge layer (wired in Phase 3)."""

    enabled: bool = False
    judges: list[str] = field(default_factory=list)  # e.g. ["faithfulness", "correctness"]
    model_role: str = "judge"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> JudgePolicy:
        d = d or {}
        return cls(
            enabled=bool(d.get("enabled", False)),
            judges=list(d.get("judges", [])),
            model_role=str(d.get("model_role", "judge")),
        )


@dataclass
class Recipe:
    """A fully-resolved recipe (one agent-centric retrieve→generate pipeline).

    There is one engine: a LlamaIndex ``FunctionAgent``. A recipe is just its
    configuration — the toolset + system prompt define the technique (naive RAG = the
    agent with one ``ema_search`` tool; CRAG = the agent + ``corrective_search``; etc.).
    """

    name: str
    label: str = ""
    description: str = ""
    default: bool = False
    # orchestration
    system_prompt: str = "agent_regulatory.md"
    tools: list[str] = field(default_factory=lambda: ["ema_search"])
    output_schema: str = "RegulatoryAnswer"
    # retrieval
    index_profile: str = "neo4j_hier"
    pipeline: str | None = None  # configs/retrieval/<name>.yaml, or None = plain retrieve
    fewshot: FewshotPolicy = field(default_factory=FewshotPolicy)
    # generation
    model: str = "claude_opus"  # models.yaml model name
    temperature: float = 0.0
    # judge
    judge: JudgePolicy = field(default_factory=JudgePolicy)

    @property
    def display_label(self) -> str:
        return self.label or self.name

    def resolved_attributes(
        self,
        *,
        model: str | None = None,
        temperature: float | None = None,
        retrieval_k: int | None = None,
    ) -> dict[str, Any]:
        """Flatten the *effective* config to ``ema.*`` trace attributes (honest stamping).

        ``model``/``temperature``/``retrieval_k`` are the live values actually used for the
        run (the settings-panel overrides resolved by ``build_recipe``); when given they are
        stamped instead of the recipe defaults, so the trace reflects what truly ran — not
        what the YAML declared. ``retrieval_k`` is only stamped when supplied.

        The few-shot / judge *policy* flags are stamped (they describe what the recipe is
        configured to do); per-stage detail is only added when that stage is enabled, so a
        disabled stage reads simply as ``ema.fewshot.enabled=False`` rather than implying it
        ran. The runtime confirmation (``ema.fewshot.injected``, judge scores) is stamped
        separately by the adapter / app at turn time.
        """
        from harness.obs import resolved_config_attributes

        eff_model = model or self.model
        eff_temp = temperature if temperature is not None else self.temperature

        fewshot: dict[str, Any] = {"enabled": self.fewshot.enabled}
        if self.fewshot.enabled:
            fewshot.update(
                {
                    "source": self.fewshot.source,
                    "k": self.fewshot.k,
                    "min_rating": self.fewshot.min_rating,
                    "min_examples": self.fewshot.min_examples,
                }
            )
        judge: dict[str, Any] = {"enabled": self.judge.enabled}
        if self.judge.enabled:
            judge.update({"judges": self.judge.judges, "model_role": self.judge.model_role})

        retrieval: dict[str, Any] = {
            "index_profile": self.index_profile,
            "pipeline": self.pipeline or "none",
        }
        if retrieval_k is not None:
            retrieval["k"] = retrieval_k

        return resolved_config_attributes(
            {
                "recipe": self.name,
                "orchestration": {
                    "engine": "agent",
                    "tools": self.tools,
                    "output_schema": self.output_schema,
                },
                "retrieval": retrieval,
                "generation": {"model": eff_model, "temperature": eff_temp},
                "fewshot": fewshot,
                "judge": judge,
            }
        )


def _normalize_pipeline(value: Any) -> str | None:
    if value in (None, "", "none", "None"):
        return None
    return str(value)


def _recipe_from_dict(name: str, d: dict[str, Any]) -> Recipe:
    orch = d.get("orchestration", {}) or {}
    retr = d.get("retrieval", {}) or {}
    gen = d.get("generation", {}) or {}

    return Recipe(
        name=name,
        label=str(d.get("label", "")),
        description=str(d.get("description", "")),
        default=bool(d.get("default", False)),
        system_prompt=orch.get("system_prompt", "agent_regulatory.md"),
        tools=list(orch.get("tools", ["ema_search"])),
        output_schema=orch.get("output_schema", "RegulatoryAnswer"),
        index_profile=retr.get("index_profile", "neo4j_hier"),
        pipeline=_normalize_pipeline(retr.get("pipeline")),
        fewshot=FewshotPolicy.from_dict(retr.get("fewshot")),
        model=gen.get("model", "claude_opus"),
        temperature=float(gen.get("temperature", 0.0)),
        judge=JudgePolicy.from_dict(d.get("judge")),
    )


def load_recipe(name: str) -> Recipe:
    """Load ``recipes/<name>.yaml`` (external dir wins over built-in) into a ``Recipe``."""
    path = find_config("recipes", f"{name}.yaml")
    if path is None:
        raise FileNotFoundError(
            f"Recipe not found: {name!r} (searched $EMA_CONFIG_DIR/recipes and the built-in recipes/)"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _recipe_from_dict(name, raw.get("recipe", raw))
