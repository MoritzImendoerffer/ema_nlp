"""Recipe registry — discover recipes across the config search path.

The Chainlit dropdown and any CLI read this, so a recipe dropped into
``$EMA_CONFIG_DIR/recipes/`` (or added to the built-in ``harness/configs/recipes/``)
appears automatically with no code change.
"""

from __future__ import annotations

from harness.config_paths import list_config_stems
from harness.recipes.config import Recipe, load_recipe


def list_recipes() -> list[str]:
    """Sorted recipe names available across the search path."""
    return list_config_stems("recipes")


def get_recipe(name: str) -> Recipe:
    """Load a single recipe by name."""
    return load_recipe(name)


def load_all_recipes() -> list[Recipe]:
    """Load every available recipe (for the dropdown: name/label/description)."""
    return [load_recipe(n) for n in list_recipes()]


def default_recipe_name() -> str | None:
    """Name of the recipe flagged ``default: true``, else the first by name, else None."""
    names = list_recipes()
    for n in names:
        if load_recipe(n).default:
            return n
    return names[0] if names else None
