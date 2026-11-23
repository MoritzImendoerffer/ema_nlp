"""LLM judges for ``mlflow.genai`` (faithfulness / correctness) + alignment driver.

``build_judge`` wraps ``mlflow.genai.judges.make_judge`` (lazy); ``ema_judges`` builds
the project's faithfulness + correctness judges from the prompts in
``harness/judges/*.md``. ``align_judge`` runs MLflow judge alignment (the reward
calibration) against traces that carry paired human + judge assessments.

Runtime-verified later (needs mlflow + an LLM; alignment needs >=10 paired labels).
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

JUDGES_DIR = Path(__file__).parent.parent / "judges"
JUDGE_NAMES = ("faithfulness", "correctness")

# The harness/judges/*.md prompts use these template vars (shared with the legacy
# string-templated harness.judge). mlflow.genai.make_judge only allows the reserved
# vars inputs/outputs/expectations/trace/conversation, so map onto those at build time
# (the .md files stay the human-readable source of truth, untouched).
#
# ``context`` maps to ``outputs`` — NOT ``inputs`` — because the retrieved passages
# are produced by the run, not part of the dataset row: ``build_predict_fn`` returns
# them as ``context_passages`` in the prediction dict, so the faithfulness judge
# grades against the real retrieval (F3; mapping it to ``inputs`` starved the judge
# of context and made its scores meaningless).
_VAR_MAP = {
    "question": "inputs",
    "context": "outputs",
    "answer": "outputs",
    "gold_answer": "expectations",
}


def load_judge_instructions(name: str) -> str:
    """Read a judge instruction prompt from ``harness/judges/<name>.md``."""
    path = JUDGES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Judge prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def to_mlflow_instructions(instructions: str) -> str:
    """Rewrite ``{{custom}}`` prompt vars to mlflow's reserved ``{{ reserved }}`` set.

    Pure (offline-testable). Unknown vars are left untouched so make_judge surfaces them.
    """

    def repl(match: re.Match[str]) -> str:
        var = match.group(1).strip()
        return "{{ " + _VAR_MAP.get(var, var) + " }}"

    return re.sub(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", repl, instructions)


def _anthropic_judge_base_url(model: str) -> str | None:
    """Full Anthropic *messages* endpoint when a gateway base URL is configured.

    mlflow's judge gateway adapter uses ``base_url`` verbatim as the endpoint, so it
    needs the ``/v1/messages`` path (not just the host). Returns None for the default
    (real Anthropic) endpoint when ``ANTHROPIC_BASE_URL`` is unset.
    """
    base = os.getenv("ANTHROPIC_BASE_URL")
    if base and model.lower().startswith("anthropic"):
        return base.rstrip("/") + "/v1/messages"
    return None


def build_judge(name: str, instructions: str, *, model: str, **kwargs: Any) -> Any:
    """Build an ``mlflow.genai`` judge (lazy import).

    ``model`` is a provider-qualified id, e.g. ``"anthropic:/<model>"`` —
    keep the judge model distinct from the generator to avoid self-preference bias.
    Prompt vars are mapped to mlflow's reserved set and, when an ``ANTHROPIC_BASE_URL``
    gateway is configured, requests are routed to its messages endpoint. An Anthropic
    judge sends the workspace header when ``ANTHROPIC_WORKSPACE_ID`` is set.
    """
    from mlflow.genai.judges import make_judge

    if "base_url" not in kwargs:
        base_url = _anthropic_judge_base_url(model)
        if base_url is not None:
            kwargs["base_url"] = base_url
    if model.lower().startswith("anthropic") and "extra_headers" not in kwargs:
        from harness.models import anthropic_headers

        # mlflow 3.14.0 adds extra_headers to the judge's request (gateway_adapter.py:553).
        if headers := anthropic_headers():
            kwargs["extra_headers"] = headers
    return make_judge(name=name, instructions=to_mlflow_instructions(instructions), model=model, **kwargs)


# models.yaml provider -> the provider name of mlflow 3.14.0's judge adapter
# (mlflow/metrics/genai/model_utils.py). mlflow knows neither 'together_ai' nor
# 'openai_compatible', and an unknown name fails only on the first judge call.
_MLFLOW_PROVIDER = {
    "anthropic": "anthropic",
    "together_ai": "togetherai",
    "openai_compatible": "openai",
}


@dataclass(frozen=True)
class JudgeRoute:
    """What an mlflow judge needs to reach one models.yaml entry.

    ``model`` is mlflow's ``provider:/model_id``. ``base_url`` is the endpoint, used by
    mlflow verbatim (``gateway_adapter.py:546``), or None for the provider's default.
    ``key_env`` is ``(variable this repository sets, variable mlflow reads)`` when the
    two differ, else None. ``model_id`` is the entry's model id, which runs are tagged with.
    """

    model: str
    base_url: str | None = None
    key_env: tuple[str, str] | None = None
    model_id: str = ""


def judge_route(cfg: Any) -> JudgeRoute:
    """The judge route for a :class:`harness.models.ModelConfig` (pure).

    - ``anthropic``: the key is ``ANTHROPIC_API_KEY`` for both; the endpoint is set by
      :func:`build_judge` when ``ANTHROPIC_BASE_URL`` names a gateway.
    - ``together_ai`` -> ``togetherai``: mlflow reads ``TOGETHERAI_API_KEY``
      (``model_utils.py:430``); this repository sets ``TOGETHER_API_KEY``.
    - ``openai_compatible`` -> ``openai``: mlflow requires ``OPENAI_API_KEY``
      (``model_utils.py:349-354``); the entry names its own variable in ``api_key_env``.
      The endpoint is the entry's ``api_base`` plus ``/chat/completions``.

    Raises ``ValueError`` for a provider mlflow cannot serve as a judge.
    """
    provider = _MLFLOW_PROVIDER.get(cfg.provider)
    if provider is None:
        raise ValueError(
            f"No mlflow judge route for provider {cfg.provider!r} (model {cfg.model_name!r}); "
            f"known providers: {sorted(_MLFLOW_PROVIDER)}"
        )
    model = f"{provider}:/{cfg.model_id}"
    if cfg.provider == "together_ai":
        return JudgeRoute(
            model, key_env=("TOGETHER_API_KEY", "TOGETHERAI_API_KEY"), model_id=cfg.model_id
        )
    if cfg.provider == "openai_compatible":
        base = (cfg.api_base or "http://localhost:8000/v1").rstrip("/") + "/chat/completions"
        key_env = (cfg.api_key_env or "OPENAI_API_KEY", "OPENAI_API_KEY")
        return JudgeRoute(model, base_url=base, key_env=key_env, model_id=cfg.model_id)
    return JudgeRoute(model, model_id=cfg.model_id)


def resolve_judge_route(role: str = "judge", *, model_key: str | None = None) -> JudgeRoute:
    """The judge route of ``model_key`` when given, else of the models.yaml ``role``.

    The one place the eval runner resolves its judge (``resolve_models``): the same
    ``models.yaml`` binding the rest of the harness uses.
    """
    from harness.models import load_model_config, load_model_for_role

    cfg = load_model_config(model_key) if model_key else load_model_for_role(role)
    return judge_route(cfg)


def apply_judge_key(route: JudgeRoute) -> None:
    """Copy the route's key into the variable mlflow reads, inside this process.

    Risk: for ``openai_compatible`` this replaces ``OPENAI_API_KEY`` for the rest of
    the process. Nothing else in this repository reads ``OPENAI_API_KEY`` except as
    the default of ``api_key_env``. Only variable names are logged, never a value.
    """
    if route.key_env is None:
        return
    source, target = route.key_env
    if source == target:
        return
    value = os.getenv(source)
    if value is None:
        log.warning("judge key: %s is unset, so %s is not set from it", source, target)
        return
    os.environ[target] = value
    log.info("judge key: %s copied to %s for this process", source, target)


def ema_judges(*, model: str | None = None, route: JudgeRoute | None = None) -> list:
    """Build the project's faithfulness + correctness judges from the prompt files.

    Give either ``model`` (an mlflow ``provider:/model_id``) or a ``route``; a route also
    sets the judge's key variable and endpoint.

    Both judges ask for an integer (``feedback_value_type=int``). Without it mlflow
    stores the value as text, and three stored values were text such as
    ``" agent errored"``, which the mean then skipped without a count. A real call with
    ``anthropic:/claude-opus-5-5`` on 2026-11-23 returned ``5`` as ``int`` with the
    present prompts.
    """
    if (model is None) == (route is None):
        raise ValueError("ema_judges needs exactly one of model= or route=")
    kwargs: dict[str, Any] = {"feedback_value_type": int}
    if route is not None:
        apply_judge_key(route)
        model = route.model
        if route.base_url is not None:
            kwargs["base_url"] = route.base_url
    return [build_judge(n, load_judge_instructions(n), model=model, **kwargs) for n in JUDGE_NAMES]


def align_judge(judge: Any, traces: Any) -> Any:
    """Align ``judge`` to human feedback (SIMBA/MemAlign) using labelled traces.

    Needs traces with both a judge assessment and a human assessment of the *same*
    name (>=10, ideally 50-100). Tuned on the live MLflow store.
    """
    align = getattr(judge, "align", None)
    if align is None:
        raise NotImplementedError(
            "This mlflow build's judge has no .align(); use mlflow.genai.optimize / "
            "the alignment optimizer API for your mlflow version."
        )
    return align(traces)
