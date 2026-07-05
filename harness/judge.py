"""
LLM-based judge for faithfulness and correctness of generated answers.

Two prompts live in harness/judges/:
    faithfulness.md  — is the answer supported by the retrieved context?
    correctness.md   — does the answer match the gold answer?

The judge model is configured via models.yaml roles.judge (default: claude_opus).
Use claude_opus or above for reliable scoring on regulatory content — Haiku gives
nonsensical scores on edge cases.

Both prompts return {"score": 1-5, "reason": "..."}.

Usage:
    from harness.judge import Judge
    judge = Judge()
    f = judge.faithfulness(question, answer, context_passages)
    c = judge.correctness(question, answer, gold_answer)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)

JUDGES_DIR = Path(__file__).parent / "judges"
_MAX_TOKENS = 512


class JudgeScore(TypedDict):
    score: int  # 1–5
    reason: str


def _load_prompt(name: str) -> str:
    path = JUDGES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Judge prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def _render_prompt(template: str, **kwargs: str) -> str:
    """Replace {{key}} placeholders in *template*."""
    for key, value in kwargs.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template


def _parse_score(text: str) -> JudgeScore:
    """Extract JSON score from LLM response (strips accidental markdown fences)."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        data = json.loads(text)
        return JudgeScore(score=int(data["score"]), reason=str(data.get("reason", "")))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.warning("Could not parse judge response: %s — %s", text[:120], exc)
        return JudgeScore(score=0, reason=f"parse_error: {text[:80]}")


class Judge:
    """LLM judge backed by a models.yaml role (default: the 'judge' role)."""

    def __init__(self, llm: Any = None, *, model_role: str = "judge") -> None:
        if llm is None:
            from harness.llms import get_llm
            llm = get_llm(model_role)
        self._llm = llm
        self._faithfulness_tmpl = _load_prompt("faithfulness")
        self._correctness_tmpl = _load_prompt("correctness")

    def _call(self, prompt: str) -> str:
        from llama_index.core.llms import ChatMessage, MessageRole
        response = self._llm.chat(
            [ChatMessage(role=MessageRole.USER, content=prompt)]
        )
        return response.message.content or ""

    @staticmethod
    def _is_non_answer(answer: str) -> bool:
        stripped = answer.strip().lower()
        return stripped in {
            "no answer generated.",
            "no answer generated",
            "no answer found.",
            "no answer found",
            "",
        }

    def faithfulness(
        self,
        question: str,
        answer: str,
        context_passages: list[str],
    ) -> JudgeScore:
        """Score how faithfully *answer* is grounded in *context_passages* (1–5)."""
        if self._is_non_answer(answer):
            return JudgeScore(score=0, reason="answer_generation_failed")
        context = "\n\n---\n\n".join(context_passages) if context_passages else "(no context)"
        prompt = _render_prompt(
            self._faithfulness_tmpl,
            context=context,
            question=question,
            answer=answer,
        )
        raw = self._call(prompt)
        return _parse_score(raw)

    def correctness(
        self,
        question: str,
        answer: str,
        gold_answer: str,
    ) -> JudgeScore:
        """Score how correct *answer* is relative to *gold_answer* (1–5)."""
        if self._is_non_answer(answer):
            return JudgeScore(score=0, reason="answer_generation_failed")
        prompt = _render_prompt(
            self._correctness_tmpl,
            question=question,
            answer=answer,
            gold_answer=gold_answer,
        )
        raw = self._call(prompt)
        return _parse_score(raw)

    def score_item(
        self,
        question: str,
        answer: str,
        gold_answer: str,
        context_passages: list[str],
    ) -> dict[str, JudgeScore]:
        """Run both judges and return {"faithfulness": ..., "correctness": ...}."""
        return {
            "faithfulness": self.faithfulness(question, answer, context_passages),
            "correctness": self.correctness(question, answer, gold_answer),
        }
