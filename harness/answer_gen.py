"""
LLM answer generator for Ablation C (3×3 prompting matrix).

Given a question and a list of retrieved Q&A documents, calls a model to generate
an answer using one of three prompting strategies:
  - zero_shot   — base instruction prompt, no examples
  - few_shot    — SME-written examples prepended to system prompt
  - cot_self    — Medprompt-style CoT: model reasons step-by-step before answering

Prompt files live in harness/prompts/:
  system_zero_shot.md
  system_few_shot_sme.md
  system_cot_self.md
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import anthropic

from harness.providers import get_llm_model
from harness.models import load_tier, call_model, TIER_MID, TIER_FRONTIER, TIER_OLMO

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

_PROMPT_FILES = {
    "zero_shot": "system_zero_shot.md",
    "few_shot": "system_few_shot_sme.md",
    "cot_self": "system_cot_self.md",
}


def _load_system_prompt(strategy: str) -> str:
    fname = _PROMPT_FILES.get(strategy)
    if fname is None:
        raise ValueError(f"Unknown prompting strategy: {strategy!r}. Choose from: {list(_PROMPT_FILES)}")
    path = PROMPTS_DIR / fname
    return path.read_text(encoding="utf-8")


def _format_context(retrieved_docs: list[dict]) -> str:
    """Format retrieved Q&A docs into a context block for the LLM."""
    if not retrieved_docs:
        return "No relevant documents retrieved."
    lines: list[str] = ["## Retrieved Q&A documents", ""]
    for i, doc in enumerate(retrieved_docs, 1):
        qa_id = doc.get("qa_id", "unknown")
        source = doc.get("source_title") or doc.get("source_url") or "unknown source"
        score = doc.get("score", 0.0)
        text = doc.get("text", "")
        lines.append(f"[{i}] qa_id: {qa_id} | source: {source} | relevance score: {score:.3f}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _extract_answer_text(raw: str, strategy: str) -> str:
    """Extract just the answer text from the raw LLM response."""
    if strategy == "cot_self":
        # Strip the <reasoning>...</reasoning> block
        raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL).strip()
        # Strip "Answer:" prefix if present
        if raw.startswith("Answer:"):
            raw = raw[len("Answer:"):].strip()
    return raw.strip()


def generate_answer(
    question: str,
    retrieved_docs: list[dict],
    *,
    strategy: str = "zero_shot",
    tier_id: str = TIER_MID,
    max_tokens: int = 1024,
) -> dict:
    """
    Generate an answer for *question* using *retrieved_docs* and the specified strategy.

    Args:
        question:       The benchmark question.
        retrieved_docs: List of dicts with keys: qa_id, source_title, source_url, score, text.
        strategy:       Prompting strategy: "zero_shot" | "few_shot" | "cot_self".
        tier_id:        Model tier: TIER_MID | TIER_FRONTIER | TIER_OLMO.
        max_tokens:     Max output tokens.

    Returns:
        dict with keys: answer_text, raw_response, strategy, tier_id.
    """
    system_prompt = _load_system_prompt(strategy)
    context = _format_context(retrieved_docs)

    user_message = f"{context}\n\n---\n\nQuestion: {question}"

    raw = call_model(
        prompt=user_message,
        system=system_prompt,
        tier_id=tier_id,
        max_tokens=max_tokens,
    )

    answer_text = _extract_answer_text(raw, strategy)

    return {
        "answer_text": answer_text,
        "raw_response": raw,
        "strategy": strategy,
        "tier_id": tier_id,
    }
