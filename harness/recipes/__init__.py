"""Recipes — the single config-driven description of a retrieve→generate pipeline.

A recipe (``configs/recipes/<name>.yaml`` or ``$EMA_CONFIG_DIR/recipes/<name>.yaml``)
configures the single engine (a ``FunctionAgent``): orchestration (prompt + tools +
output schema) + retrieval (index profile + pipeline + few-shot) + generation (model +
temperature) + an optional judge layer. ``build_recipe`` composes it into a runnable
agent. See ``docs/RECIPES.md`` and ``docs/RAG_TECHNIQUES.md``.
"""

from harness.recipes.build import build_recipe
from harness.recipes.config import FewshotPolicy, JudgePolicy, Recipe, load_recipe
from harness.recipes.registry import (
    default_recipe_name,
    get_recipe,
    list_recipes,
    load_all_recipes,
)

__all__ = [
    "FewshotPolicy",
    "JudgePolicy",
    "Recipe",
    "build_recipe",
    "default_recipe_name",
    "get_recipe",
    "list_recipes",
    "load_all_recipes",
    "load_recipe",
]
