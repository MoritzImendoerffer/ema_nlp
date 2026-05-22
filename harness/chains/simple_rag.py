"""
LCEL simple RAG chains for the three prompting strategies used in Ablation C.

All three chains share the same retrieve → format → prompt → LLM → parse
structure but differ in the system prompt and post-processing step:

    zero_shot  — base instruction, no examples (system_zero_shot.md)
    few_shot   — SME-written Q&A examples prepended (system_few_shot_sme.md)
    cot_self   — Medprompt-style CoT: model reasons inside <reasoning> tags
                 before writing the final answer (system_cot_self.md)

All chains accept {"question": str} and return:
    {"answer_text": str, "strategy": str, "docs": list[Document]}

LangSmith traces automatically when LANGCHAIN_TRACING_V2=true and
LANGCHAIN_PROJECT env vars are set.

Usage::

    from harness.chains.simple_rag import build_rag_chain
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm
    from harness.embed import build_index

    index = build_index(corpus_path, index_dir)
    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")

    chain = build_rag_chain("cot_self", retriever=retriever, llm=llm)
    result = chain.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough  # noqa: F401

from harness.chains.retriever import EMARetriever

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_PROMPT_FILES: dict[str, str] = {
    "zero_shot": "system_zero_shot.md",
    "few_shot": "system_few_shot_sme.md",
    "cot_self": "system_cot_self.md",
}


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_rag_chain(
    strategy: str,
    *,
    retriever: EMARetriever,
    llm: Any,
) -> Runnable:
    """
    Build and return a LCEL RAG chain for the given prompting strategy.

    Args:
        strategy:  "zero_shot" | "few_shot" | "cot_self"
        retriever: EMARetriever instance (wraps LlamaIndex FAISS+BM25 index)
        llm:       LangChain BaseChatModel (from get_langchain_llm())

    Returns:
        A LangChain Runnable that accepts {"question": str} and returns
        {"answer_text": str, "strategy": str, "docs": list[Document]}.
    """
    if strategy not in _PROMPT_FILES:
        raise ValueError(
            f"Unknown strategy {strategy!r}. Choose from: {list(_PROMPT_FILES)}"
        )

    system_prompt = load_system_prompt(strategy)
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{context}\n\n---\n\nQuestion: {question}"),
    ])

    # Single-pass LCEL pipeline: retrieve once, forward docs to both LLM and output
    #
    #  {"question": str}
    #    → assign(docs=retrieve)               → {question, docs}
    #    → assign(context=format_docs)         → {question, docs, context}
    #    → assign(raw_response=prompt|llm|str) → {question, docs, context, raw_response}
    #    → assign(answer_text=extract)         → full output dict
    #    → pick final keys

    _retrieve = RunnableLambda(
        lambda x: retriever.invoke(x["question"]),
        name="ema_retrieve",
    )

    chain = (
        RunnablePassthrough.assign(docs=_retrieve)
        | RunnablePassthrough.assign(context=RunnableLambda(lambda x: format_docs(x["docs"])))
        | RunnablePassthrough.assign(raw_response=prompt | llm | StrOutputParser())
        | RunnableLambda(lambda x: {
            "answer_text": extract_answer(x["raw_response"], strategy),
            "raw_response": x["raw_response"],
            "prompt_strategy": strategy,
            "docs": x["docs"],
        })
    )

    return chain.with_config(run_name=f"ema_rag_{strategy}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def load_system_prompt(strategy: str) -> str:
    fname = _PROMPT_FILES[strategy]
    return (PROMPTS_DIR / fname).read_text(encoding="utf-8")


def format_docs(docs: list[Document]) -> str:
    if not docs:
        return "No relevant documents retrieved."
    lines: list[str] = ["## Retrieved Q&A documents", ""]
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        qa_id = meta.get("qa_id", "unknown")
        source = meta.get("source_title") or meta.get("source_url") or "unknown source"
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id: {qa_id} | source: {source} | relevance score: {score:.3f}")
        lines.append(doc.page_content)
        lines.append("")
    return "\n".join(lines)


def extract_answer(raw: str, strategy: str) -> str:
    """Strip CoT reasoning block and clean up the answer text."""
    if strategy == "cot_self":
        raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL).strip()
        if raw.startswith("Answer:"):
            raw = raw[len("Answer:"):].strip()
    result = raw.strip()
    return result if result else "No answer generated."
