"""Config search path: built-in package configs + an optional external dir.

Lets users keep recipes and prompts OUTSIDE the source tree. For a namespace
(``recipes``, ``prompts``, ``agent``, …), files are looked up in
``$EMA_CONFIG_DIR/<namespace>/`` first (if the env var is set), then the built-in
``harness/configs/<namespace>/`` (or ``harness/prompts/`` for prompts). External
entries therefore *override* built-ins of the same name, and new external files are
discovered automatically — so a user can add or shadow a recipe without touching the
package source.
"""

from __future__ import annotations

import os
from pathlib import Path

_PKG_ROOT = Path(__file__).parent
_BUILTIN_CONFIGS = _PKG_ROOT / "configs"
_BUILTIN_PROMPTS = _PKG_ROOT / "prompts"


def _builtin_dir(namespace: str) -> Path:
    """Built-in directory for a namespace (prompts live outside configs/)."""
    return _BUILTIN_PROMPTS if namespace == "prompts" else _BUILTIN_CONFIGS / namespace


def external_root() -> Path | None:
    """The user's external config root (``$EMA_CONFIG_DIR``), or None if unset."""
    root = os.getenv("EMA_CONFIG_DIR")
    return Path(root).expanduser() if root else None


def search_dirs(namespace: str) -> list[Path]:
    """Directories to search for ``namespace``, highest precedence first."""
    dirs: list[Path] = []
    root = external_root()
    if root is not None:
        dirs.append(root / namespace)
    dirs.append(_builtin_dir(namespace))
    return dirs


def find_config(namespace: str, filename: str) -> Path | None:
    """First existing ``namespace/filename`` across the search path, or None."""
    for d in search_dirs(namespace):
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


def list_config_stems(namespace: str, suffix: str = ".yaml") -> list[str]:
    """Sorted, de-duplicated config names across the search path.

    An external file shadows a built-in one of the same stem (it is simply listed
    once); the union is returned so external-only files appear too.
    """
    stems: set[str] = set()
    for d in search_dirs(namespace):
        if d.exists():
            stems.update(p.stem for p in d.glob(f"*{suffix}"))
    return sorted(stems)
