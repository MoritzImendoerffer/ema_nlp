"""
Typed event classes for LlamaIndex Workflow steps.

All events are Pydantic models (via llama_index.core.workflow.Event).
They carry data between workflow steps; the Workflow engine routes
each event to the step whose type annotation matches.

Event flow by strategy:

  SimpleRAG:        StartEvent → [retrieve+generate] → StopEvent
  CRAG:             StartEvent → retrieve → RetrievedEvent
                      → grade → GradeEvent | InsufficientEvent
                      GradeEvent → generate → StopEvent
                      InsufficientEvent → rewrite → _loop → retrieve
  SummarizeRAG:     StartEvent → retrieve → RetrievedEvent
                      → summarize → SummarizedEvent → generate → StopEvent
  CRAGSummarize:    CRAG loop → SummarizedEvent → generate → StopEvent
  CRAGReview:       CRAG loop → generate → GeneratedEvent
                      → review → ReviewedEvent | StopEvent
  ReactReview:      react → GeneratedEvent → review → StopEvent
"""

from __future__ import annotations

from llama_index.core.workflow import Event


class RetrievedEvent(Event):
    """Emitted after retrieval; routed to grade or summarize/generate."""
    question: str
    few_shot_context: str
    docs: list  # list[TextNode] — built from (qa_id, score, metadata) results
    rewrite_cycles: int = 0


class GradeEvent(Event):
    """Emitted when docs are sufficient; routes to generate (or summarize)."""
    question: str
    few_shot_context: str
    docs: list
    rewrite_cycles: int
    graded_docs: list = []  # per-doc score dicts [{qa_id, score}, ...] for Phoenix spans


class InsufficientEvent(Event):
    """Emitted when docs are insufficient; routes to rewrite."""
    question: str
    few_shot_context: str
    rewrite_cycles: int
    missing_facts: list = []  # facts the retrieved docs do not cover


class GeneratedEvent(Event):
    """Emitted after answer generation; used in composite review workflows."""
    answer_text: str
    docs: list
    question: str
    prompt_strategy: str


class ReviewedEvent(Event):
    """Emitted after faithfulness review; carries score and pass/fail."""
    score: float
    feedback: str
    passed: bool
    answer_text: str
    docs: list


class SummarizedEvent(Event):
    """Emitted after document summarization; routes to generate."""
    summary: str
    docs: list
    question: str
    few_shot_context: str = ""


# ReAct native workflow events (react_native.py)

class ThoughtEvent(Event):
    """Emitted after a think step; carries parsed thought + tool call or None."""
    thought: str
    tool_name: str | None    # None → agent has an answer
    tool_args: str
    question: str
    history: list            # accumulated ChatMessage-like dicts for context
    iteration: int
    cited_qa_ids: list
    docs_snapshot: list      # most recent retrieved docs


class ActionEvent(Event):
    """Emitted after a tool call; carries the raw tool result."""
    tool_name: str
    tool_result: str
    docs_snapshot: list
    question: str
    history: list
    iteration: int
    cited_qa_ids: list


class ObservationEvent(Event):
    """Emitted after observe step; loops back to think."""
    observation: str
    question: str
    history: list
    iteration: int
    cited_qa_ids: list
    docs_snapshot: list


class FinishEvent(Event):
    """Emitted by think when the agent has a final answer; routes to StopEvent."""
    answer_text: str
    cited_qa_ids: list
    docs: list
    history: list
