"""Evaluation + reward + optimization layer (aim 1).

- ``predict``  — adapt a recipe adapter / agent / session to an mlflow.genai predict_fn
- ``judges``   — mlflow.genai LLM judges (faithfulness/correctness) + alignment
- ``evaluate`` — run mlflow.genai evaluation
- ``runner``   — recipe × benchmark → per-type MLflow runs (the R6 vehicle)
- ``bootstrap``— teacher -> judge-filter -> DSPy few-shot compilation

See ``docs/TARGET_ARCHITECTURE.md`` §4.6. The reward signal is an *aligned* judge;
DSPy is the optimizer; the agent few-shot is the policy.
"""

from harness.eval.bootstrap import (
    Exemplar,
    compile_fewshot,
    faithfulness_judge,
    generate_exemplars,
    judge_filter,
)
from harness.eval.evaluate import run_evaluation
from harness.eval.inline_judge import (
    JudgeResult,
    review_verdict,
    run_inline_judges,
    runtime_judges,
)
from harness.eval.judges import (
    align_judge,
    build_judge,
    ema_judges,
    load_judge_instructions,
    resolve_judge_route,
)
from harness.eval.predict import build_predict_fn, predict_items
from harness.eval.runner import (
    evaluate_items,
    format_summary,
    load_benchmark,
    run_recipe_benchmark,
)

__all__ = [
    "Exemplar",
    "JudgeResult",
    "align_judge",
    "build_judge",
    "build_predict_fn",
    "compile_fewshot",
    "ema_judges",
    "evaluate_items",
    "faithfulness_judge",
    "format_summary",
    "generate_exemplars",
    "judge_filter",
    "load_benchmark",
    "load_judge_instructions",
    "predict_items",
    "resolve_judge_route",
    "review_verdict",
    "run_evaluation",
    "run_inline_judges",
    "run_recipe_benchmark",
    "runtime_judges",
]
