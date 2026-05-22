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
    docs: list  # list[Doc] — built from (qa_id, score, metadata) results
    rewrite_cycles: int = 0


class GradeEvent(Event):
    """Emitted when docs are sufficient; routes to generate (or summarize)."""
    question: str
    few_shot_context: str
    docs: list
    rewrite_cycles: int


class InsufficientEvent(Event):
    """Emitted when docs are insufficient; routes to rewrite."""
    question: str
    few_shot_context: str
    rewrite_cycles: int


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
