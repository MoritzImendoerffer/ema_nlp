# EMA Q&A Assistant

Ask any question about European Medicines Agency (EMA) human-regulatory guidance.

**Features:**
- Hierarchical retrieval over the EMA regulatory corpus — a Neo4j `PropertyGraphIndex` of parsed EMA documents (HTML pages + PDFs / EPARs), searched by BGE-large dense embeddings with small-to-big merge-up and 1-hop `LINKS_TO` graph expansion
- Streaming answers grounded in retrieved passages
- Source provenance — see referenced EMA documents in the sidebar
- Choose a retrieval+reasoning workflow per session: single-step `simple_rag` or multi-step agents (CRAG, ReAct, summarize, review variants); multi-step workflows show their intermediate steps and let you rate the trajectory
- Full trace visibility via [Arize Phoenix](http://localhost:6006) (if running), with 👍/👎 feedback written back as Phoenix annotations

**Configuration:**
- Retrieval setup is selected by `EMA_INDEX_PROFILE` (default `neo4j_hier`)
- The 7 registered workflows live in `harness/workflows/registry.py` — see `docs/WORKFLOWS.md`

**Example questions:**
- What are the requirements for a bioequivalence study waiver?
- How should impurities be reported in a marketing authorisation application?
- What is the acceptable intake for nitrosamine impurities?
