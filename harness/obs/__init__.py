"""Observability helpers (transparency / resolved-config stamping).

See ``docs/TARGET_ARCHITECTURE.md`` §4.7.
"""

from harness.obs.config_attrs import (
    echo_resolved_config,
    resolved_config_attributes,
    stamp_current_span,
)

__all__ = [
    "echo_resolved_config",
    "resolved_config_attributes",
    "stamp_current_span",
]
