"""LLM judges for ``mlflow.genai`` (faithfulness / correctness) + alignment driver.

``build_judge`` wraps ``mlflow.genai.judges.make_judge`` (lazy); ``ema_judges`` builds
the project's faithfulness + correctness judges from the prompts in
``harness/judges/*.md``. ``align_judge`` runs MLflow judge alignment (the reward
calibration) against traces that carry paired human + judge assessments.

Runtime-verified later (needs mlflow + an LLM; alignment needs >=10 paired labels).
"""

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

JUDGES_DIR = Path(__file__).parent.parent / "judges"
JUDGE_NAMES = ("faithfulness", "correctness")


def load_judge_instructions(name: str) -> str:
    """Read a judge instruction prompt from ``harness/judges/<name>.md``."""
    path = JUDGES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Judge prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def build_judge(name: str, instructions: str, *, model: str, **kwargs: Any) -> Any:
    """Build an ``mlflow.genai`` judge (lazy import).

    ``model`` is a provider-qualified id, e.g. ``"anthropic:/<model>"`` —
    keep the judge model distinct from the generator to avoid self-preference bias.
    """
    from mlflow.genai.judges import make_judge

    return make_judge(name=name, instructions=instructions, model=model, **kwargs)


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
