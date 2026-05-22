"""
Corrective RAG (CRAG) LangGraph workflow (LSMT-009).

Corrective RAG improves answer quality by grading the initial retrieved documents
before generating.  If the documents are insufficient to answer the question, the
query is rewritten and retrieval is retried (up to MAX_CYCLES times).

Workflow::

    retrieve ──→ grade_relevance ──→ sufficient?  ──yes──→ generate ──→ output
                        │
                        └── no ──→ rewrite_query ──→ retrieve (loop)

The grade and rewrite nodes are LLM calls; retrieve and generate reuse
EMARetriever and the LCEL simple RAG chain respectively.

Usage::

    from harness.chains.agents.crag import build_crag
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm

    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")
    crag = build_crag(retriever=retriever, llm=llm)

    result = crag.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
    print(result["correction_cycles"])  # number of rewrites that occurred
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from harness.chains.retriever import EMARetriever
from harness.chains.simple_rag import extract_answer, format_docs, load_system_prompt

log = logging.getLogger(__name__)

MAX_CYCLES = 2  # max retrieve-rewrite iterations before forcing an answer


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class CRAGState(TypedDict):
    question: str
    docs: list[Document]
    answer_text: str
    prompt_strategy: str
    cycle: int            # number of rewrite cycles completed
    grade: str            # "sufficient" | "insufficient"


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_crag(
    *,
    retriever: EMARetriever,
    llm: Any,
    strategy: str = "zero_shot",
) -> Any:
    """
    Build and return a compiled CRAG LangGraph workflow.

    Args:
        retriever: EMARetriever instance.
        llm:       LangChain BaseChatModel.
        strategy:  Answer generation strategy: "zero_shot" | "few_shot" | "cot_self".

    Returns:
        A compiled workflow whose invoke/ainvoke accepts {"question": str} and
        returns {"answer_text": str, "docs": list[Document], "correction_cycles": int, "strategy": str}.
    """
    system_prompt = load_system_prompt(strategy)

    # ---- Grade node ----
    _grade_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a relevance grader for EMA regulatory Q&A retrieval. "
         "Your only job is to decide whether the retrieved documents contain "
         "enough information to answer the question.\n\n"
         "Respond with exactly one word: 'sufficient' or 'insufficient'.\n"
         "Do not explain your reasoning."),
        ("human",
         "Question: {question}\n\nRetrieved documents:\n{context}\n\n"
         "Are these documents sufficient to answer the question?"),
    ])
    _grade_chain = _grade_prompt | llm | StrOutputParser()

    def grade_relevance(state: CRAGState) -> dict:
        context = format_docs(state["docs"])
        raw = _grade_chain.invoke({"question": state["question"], "context": context})
        raw_lower = raw.lower().strip()
        grade = "sufficient" if "sufficient" in raw_lower and "insufficient" not in raw_lower else "insufficient"
        log.debug("CRAG grade (cycle=%d): %s", state["cycle"], grade)
        return {"grade": grade}

    # ---- Rewrite node ----
    _rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a query rewriter for EMA regulatory document retrieval. "
         "The original query did not retrieve sufficient documents. "
         "Rewrite it to be more specific, using EMA terminology. "
         "Return only the rewritten query, nothing else."),
        ("human", "Original query: {question}"),
    ])
    _rewrite_chain = _rewrite_prompt | llm | StrOutputParser()

    def rewrite_query(state: CRAGState) -> dict:
        new_question = _rewrite_chain.invoke({"question": state["question"]}).strip()
        log.debug("CRAG rewrite (cycle=%d): %r → %r", state["cycle"], state["question"], new_question)
        return {"question": new_question, "cycle": state["cycle"] + 1}

    # ---- Retrieve node ----
    def retrieve(state: CRAGState) -> dict:
        docs = retriever.invoke(state["question"])
        return {"docs": docs}

    # ---- Generate node ----
    _answer_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{context}\n\n---\n\nQuestion: {question}"),
    ])
    _answer_chain = _answer_prompt | llm | StrOutputParser()

    def generate(state: CRAGState) -> dict:
        context = format_docs(state["docs"])
        raw = _answer_chain.invoke({"question": state["question"], "context": context})
        return {
            "answer_text": extract_answer(raw, strategy),
            "prompt_strategy": f"crag_{strategy}",
        }

    # ---- Routing ----
    def route_after_grade(state: CRAGState) -> str:
        if state["grade"] == "sufficient" or state["cycle"] >= MAX_CYCLES:
            if state["cycle"] >= MAX_CYCLES and state["grade"] != "sufficient":
                log.warning("CRAG: max cycles (%d) reached; generating anyway", MAX_CYCLES)
            return "generate"
        return "rewrite"

    # ---- Build graph ----
    graph = StateGraph(CRAGState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade_relevance)
    graph.add_node("rewrite", rewrite_query)
    graph.add_node("generate", generate)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade, {"generate": "generate", "rewrite": "rewrite"})
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", END)

    compiled = graph.compile()

    class _CRAGWrapper:
        def invoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            state = compiled.invoke(
                {"question": question, "docs": [], "answer_text": "", "prompt_strategy": "", "cycle": 0, "grade": ""},
                **kwargs,
            )
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "docs": state.get("docs", []),
                "prompt_strategy": state.get("prompt_strategy", f"crag_{strategy}"),
                "correction_cycles": state.get("cycle", 0),
            }

        async def ainvoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            state = await compiled.ainvoke(
                {"question": question, "docs": [], "answer_text": "", "prompt_strategy": "", "cycle": 0, "grade": ""},
                **kwargs,
            )
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "docs": state.get("docs", []),
                "prompt_strategy": state.get("prompt_strategy", f"crag_{strategy}"),
                "correction_cycles": state.get("cycle", 0),
            }

        def __call__(self, inputs: dict) -> dict:
            return self.invoke(inputs)

    return _CRAGWrapper()
