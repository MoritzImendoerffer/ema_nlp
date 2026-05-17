"""
LLM-based judge for faithfulness and correctness of generated answers.

Two prompts live in harness/judges/:
    faithfulness.md  — is the answer supported by the retrieved context?
    correctness.md   — does the answer match the gold answer?

The judge uses a *different* model than the answer generator (by default
claude-haiku-4-5-20251001 for low cost during batch evaluation). Both prompts
return {"score": 1-5, "reason": "..."}.

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
from typing import TypedDict

import anthropic

from harness.providers import get_llm_model

log = logging.getLogger(__name__)

JUDGES_DIR = Path(__file__).parent / "judges"
DEFAULT_JUDGE_MODEL = get_llm_model()
_MAX_TOKENS = 256


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
    # Strip optional ```json … ``` wrapper
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        data = json.loads(text)
        return JudgeScore(score=int(data["score"]), reason=str(data.get("reason", "")))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.warning("Could not parse judge response: %s — %s", text[:120], exc)
        return JudgeScore(score=0, reason=f"parse_error: {text[:80]}")


class Judge:
    """Stateless LLM judge backed by Anthropic Claude."""

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, api_key: str | None = None) -> None:
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY env var
        self._faithfulness_tmpl = _load_prompt("faithfulness")
        self._correctness_tmpl = _load_prompt("correctness")

    def _call(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text  # type: ignore[index]

    def faithfulness(
        self,
        question: str,
        answer: str,
        context_passages: list[str],
    ) -> JudgeScore:
        """Score how faithfully *answer* is grounded in *context_passages* (1–5)."""
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
