# EMA Q&A Assistant

Ask any question about European Medicines Agency (EMA) human-regulatory guidance.

**Features:**
- Hierarchical retrieval over the EMA regulatory corpus — a Neo4j `PropertyGraphIndex` of parsed EMA documents (HTML pages + PDFs / EPARs), searched by BGE-large dense embeddings with small-to-big merge-up and 1-hop `LINKS_TO` graph expansion
- Streaming answers grounded in retrieved passages
- Source provenance — see referenced EMA documents in the sidebar
- Pick a **recipe live from the settings panel** (listed dynamically from `harness/configs/recipes/`, so a newly-added recipe appears automatically): `naive_rag` (retrieve once → answer), `crag_agentic` (corrective grade/rewrite-retry), `react_agentic`, `regulatory_agent`, `agentic_reranked`, `agentic_judged`, `regulatory_fewshot`. Model / temperature / retrieval-k / cache are live overrides
- Full trace visibility via [MLflow tracing](http://localhost:5000) (if running), with 👍/👎 feedback written back as MLflow trace assessments

**Configuration:**
- Retrieval setup is selected by `EMA_INDEX_PROFILE` (default `neo4j_hier`)
- Recipes live in `harness/configs/recipes/*.yaml` (+ `$EMA_CONFIG_DIR/recipes/`) — see `docs/RECIPES.md` + `docs/RAG_TECHNIQUES.md`

**Example questions:**
- What are the requirements for a bioequivalence study waiver?
- How should impurities be reported in a marketing authorisation application?
- What is the acceptable intake for nitrosamine impurities?
