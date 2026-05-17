# EMA Q&A Assistant

Ask any question about European Medicines Agency (EMA) human-regulatory guidance.

**Features:**
- Hybrid retrieval (dense + BM25 fusion) over EMA Q&A corpus
- Streaming answers grounded in retrieved passages
- Source provenance — see referenced EMA documents in the sidebar
- Chain-of-thought steps (Retrieval + Synthesis) with per-step ratings
- Full trace visibility via [Arize Phoenix](http://localhost:6006) (if running)

**Example questions:**
- What are the requirements for a bioequivalence study waiver?
- How should impurities be reported in a marketing authorisation application?
- What is the acceptable intake for nitrosamine impurities?
