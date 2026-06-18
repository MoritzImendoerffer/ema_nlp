"""Evaluation + reward + optimization layer (aim 1).

- ``predict``  — adapt an agent/session to an mlflow.genai predict_fn
- ``judges``   — mlflow.genai LLM judges (faithfulness/correctness) + alignment
- ``evaluate`` — run mlflow.genai evaluation
- ``bootstrap``— teacher -> judge-filter -> DSPy few-shot compilation

See ``docs/TARGET_ARCHITECTURE.md`` §4.6. The reward signal is an *aligned* judge;
DSPy is the optimizer; the agent few-shot is the policy.
"""

from harness.eval.bootstrap import Exemplar, compile_fewshot, generate_exemplars, judge_filter
from harness.eval.evaluate import run_evaluation
from harness.eval.judges import align_judge, build_judge, ema_judges, load_judge_instructions
from harness.eval.predict import build_predict_fn

__all__ = [
    "Exemplar",
    "align_judge",
    "build_judge",
    "build_predict_fn",
    "compile_fewshot",
    "ema_judges",
    "generate_exemplars",
    "judge_filter",
    "load_judge_instructions",
    "run_evaluation",
]
