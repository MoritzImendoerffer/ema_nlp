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
    gateway is configured, requests are routed to its messages endpoint.
    """
    from mlflow.genai.judges import make_judge

    if "base_url" not in kwargs:
        base_url = _anthropic_judge_base_url(model)
        if base_url is not None:
            kwargs["base_url"] = base_url
    return make_judge(name=name, instructions=to_mlflow_instructions(instructions), model=model, **kwargs)


def ema_judges(*, model: str) -> list:
    """Build the project's faithfulness + correctness judges from the prompt files."""
    return [build_judge(n, load_judge_instructions(n), model=model) for n in JUDGE_NAMES]


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
