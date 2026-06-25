"""Resolved-config → trace attributes (transparency: *no silent modes*).

The ``mode: none`` surprise (a default buried in code, invisible at runtime) is
fixed here: the *resolved* config is flattened to ``ema.*`` keys, stamped on the
current trace span, and echoed to the log. ``None``/empty values become the
explicit string ``"none"`` rather than vanishing.

Backend-agnostic: ``stamp_current_span`` uses OpenTelemetry if present (which MLflow's
tracing builds on) and silently no-ops otherwise — so this module has no hard tracing
dependency and is unit-testable with nothing installed.
"""

import logging
from typing import Any

log = logging.getLogger(__name__)

Scalar = str | int | float | bool


def _to_scalar(value: Any) -> Scalar:
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)


def resolved_config_attributes(config: dict[str, Any], *, prefix: str = "ema") -> dict[str, Scalar]:
    """Flatten a (possibly nested) config dict to dotted ``prefix.*`` scalar attrs.

    Lists become comma-joined strings; ``None`` and empty lists become ``"none"``.
    """
    out: dict[str, Scalar] = {}

    def _walk(node: dict[str, Any], pfx: str) -> None:
        for key, value in node.items():
            full = f"{pfx}.{key}"
            if isinstance(value, dict):
                _walk(value, full)
            elif isinstance(value, list | tuple):
                out[full] = ",".join(str(_to_scalar(v)) for v in value) if value else "none"
            elif value is None:
                out[full] = "none"
            else:
                out[full] = _to_scalar(value)

    _walk(config, prefix)
    return out


def stamp_current_span(attrs: dict[str, Scalar]) -> bool:
    """Best-effort: set ``attrs`` on the current OTel span. Returns True if stamped."""
    try:
        from opentelemetry import trace as otel_trace

        get_current_span = getattr(otel_trace, "get_current_span", None)
        if get_current_span is None:
            return False
        span = get_current_span()
        if span is None or not span.is_recording():
            return False
        for key, value in attrs.items():
            span.set_attribute(key, value)
        return True
    except Exception:
        return False


def echo_resolved_config(config: dict[str, Any], *, logger: logging.Logger | None = None) -> str:
    """Log and return a one-line human summary of the resolved config."""
    attrs = resolved_config_attributes(config)
    line = " | ".join(f"{k}={v}" for k, v in sorted(attrs.items()))
    (logger or log).info("resolved config: %s", line)
    return line
