"""
LangGraph ReAct agent with EMA retrieval tools (LSMT-008).

Mirrors the four tools from harness/agents/react_agent.py but runs on
LangGraph + LangChain instead of LlamaIndex's internal ReActAgent.  LangSmith
traces all tool calls and LLM steps automatically when LANGCHAIN_TRACING_V2=true.

Tools:
    ema_search(query, k)         — hybrid RRF retrieval via EMARetriever
    follow_cross_refs(qa_id)     — O(1) cross-reference traversal
    filter_by_topic(topic)       — substring filter on last search results
    format_answer(text, sources) — terminal: sets final answer and halts

Usage::

    from harness.chains.agents.react import build_react_agent
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm
    from harness.embed import build_index

    index = build_index(corpus_path, index_dir)
    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")

    agent = build_react_agent(retriever=retriever, llm=llm)
    result = agent.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
    print(result["cited_qa_ids"])
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from harness.chains.retriever import EMARetriever

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    question: str
    messages: Annotated[list[BaseMessage], add_messages]
    answer_text: str
    cited_qa_ids: list[str]
    trajectory: list[dict]


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_react_agent(
    *,
    retriever: EMARetriever,
    llm: Any,
    max_steps: int = 10,
    system_prompt: str | None = None,
) -> Any:
    """
    Build and return a compiled LangGraph ReAct agent.

    Args:
        retriever:     EMARetriever instance (wraps LlamaIndex index).
        llm:           LangChain BaseChatModel with tool-calling support.
        max_steps:     Maximum number of tool-call iterations before forcing a stop.
        system_prompt: Optional system prompt prefix (e.g. few-shot context).

    Returns:
        A compiled LangGraph StateGraph whose invoke/ainvoke signature is:
            {"question": str} → {"answer_text": str, "cited_qa_ids": list[str], "trajectory": list[dict]}
    """

    # ---- Tool definitions (capture retriever in closure) ----

    @tool
    def ema_search(query: str, k: int = 10) -> str:
        """Search the EMA Q&A corpus using hybrid RRF retrieval (dense + BM25).
        Returns the top-k relevant Q&A passages. Use this first for any question."""
        docs = retriever.invoke(query)[:k]
        # Store docs in a side-channel list so filter_by_topic can access them
        _last_docs.clear()
        _last_docs.extend(docs)
        return _format_docs_for_agent(docs)

    @tool
    def follow_cross_refs(qa_id: str) -> str:
        """Follow cross-references from a given Q&A entry (qa_id) to related entries.
        Useful when a document mentions related topics that may answer the question more fully."""
        docs = retriever.get_cross_refs(qa_id)
        if not docs:
            return f"No cross-references found for qa_id={qa_id!r}."
        return _format_docs_for_agent(docs)

    @tool
    def filter_by_topic(topic: str) -> str:
        """Filter the last search results to entries matching a topic path or URL substring.
        Use this to narrow down results when a broader search returned off-topic passages."""
        filtered = retriever.filter_by_topic(_last_docs, topic)
        if not filtered:
            return f"No results remaining after filtering by topic={topic!r}."
        _last_docs.clear()
        _last_docs.extend(filtered)
        return _format_docs_for_agent(filtered)

    @tool
    def format_answer(answer_text: str, cited_qa_ids: list[str]) -> str:
        """Format and submit the final answer. Call this when you have enough information
        to answer the question. Provide the complete answer and list of cited qa_ids."""
        return f"FINAL_ANSWER:{answer_text}|||CITED:{','.join(cited_qa_ids)}"

    # NOTE: _last_docs is a per-agent-instance mutable list used by filter_by_topic.
    # Sequential calls on the same _AgentWrapper are safe; concurrent calls are not.
    # If LangSmith parallelises evaluation, construct a separate agent per worker.
    _last_docs: list[Document] = []
    tools = [ema_search, follow_cross_refs, filter_by_topic, format_answer]
    tool_node = ToolNode(tools)
    llm_with_tools = llm.bind_tools(tools)

    # ---- Graph nodes ----

    _default_system = (
        "You are an expert on European Medicines Agency (EMA) human-regulatory procedures. "
        "Use the provided tools to find information and answer the question accurately. "
        "Always search before answering. When you have found sufficient information, "
        "call format_answer() with your final answer and the qa_ids you cited. "
        "Important: 'AI' means Acceptable Intake (ng/day), not Artificial Intelligence."
    )
    effective_system = (system_prompt + "\n\n" + _default_system) if system_prompt else _default_system

    def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        if not messages:
            messages = [HumanMessage(content=state["question"])]
        response = llm_with_tools.invoke(
            [{"role": "system", "content": effective_system}] + messages  # type: ignore[arg-type]
        )
        trajectory = list(state.get("trajectory", []))
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                trajectory.append({"type": "tool_call", "tool_name": tc["name"], "args": tc["args"]})
        return {"messages": [response], "trajectory": trajectory}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return "end"
        if hasattr(last, "tool_calls") and last.tool_calls:
            n_tool_calls = sum(
                1 for m in state["messages"]
                if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls
            )
            if n_tool_calls >= max_steps:
                log.warning("Max steps (%d) reached, forcing stop", max_steps)
                return "end"
            return "tools"
        return "end"

    def should_continue_after_tools(state: AgentState) -> str:
        """Route to extract if format_answer was just processed; otherwise loop back to agent."""
        for msg in reversed(state["messages"]):
            if isinstance(msg, ToolMessage) and "FINAL_ANSWER:" in (msg.content or ""):
                return "extract"
            if isinstance(msg, AIMessage):
                break
        return "agent"

    def extract_answer(state: AgentState) -> dict:
        """After the final tool call, extract answer_text and cited_qa_ids."""
        answer_text = "No answer generated."
        cited_qa_ids: list[str] = []
        for msg in reversed(state["messages"]):
            if isinstance(msg, ToolMessage) and "FINAL_ANSWER:" in (msg.content or ""):
                content: str = msg.content
                parts = content.split("|||CITED:")
                answer_text = parts[0].replace("FINAL_ANSWER:", "").strip()
                if len(parts) > 1:
                    cited_qa_ids = [c.strip() for c in parts[1].split(",") if c.strip()]
                break
        return {"answer_text": answer_text, "cited_qa_ids": cited_qa_ids}

    # ---- Build graph ----

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("extract", extract_answer)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": "extract"},
    )
    graph.add_conditional_edges(
        "tools",
        should_continue_after_tools,
        {"agent": "agent", "extract": "extract"},
    )
    graph.add_edge("extract", END)

    compiled = graph.compile()

    # Wrap invoke/ainvoke to expose a clean interface compatible with LCEL chains
    class _AgentWrapper:
        def invoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            state = compiled.invoke(
                {"question": question, "messages": [], "answer_text": "", "cited_qa_ids": [], "trajectory": []},
                **kwargs,
            )
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "cited_qa_ids": state.get("cited_qa_ids", []),
                "trajectory": state.get("trajectory", []),
                "docs": _last_docs[:],
                "prompt_strategy": "react",
            }

        async def ainvoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            state = await compiled.ainvoke(
                {"question": question, "messages": [], "answer_text": "", "cited_qa_ids": [], "trajectory": []},
                **kwargs,
            )
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "cited_qa_ids": state.get("cited_qa_ids", []),
                "trajectory": state.get("trajectory", []),
                "docs": _last_docs[:],
                "prompt_strategy": "react",
            }

        # Make it usable as a LangSmith target (callable)
        def __call__(self, inputs: dict) -> dict:
            return self.invoke(inputs)

    return _AgentWrapper()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_docs_for_agent(docs: list[Document]) -> str:
    if not docs:
        return "No results found."
    lines: list[str] = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        qa_id = meta.get("qa_id", "?")
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id={qa_id} score={score:.3f}")
        lines.append(doc.page_content[:400])
        lines.append("")
    return "\n".join(lines)
