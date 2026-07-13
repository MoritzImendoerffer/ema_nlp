# RAG techniques as agent tools + instructions

This project uses a **single agent-centric engine**: every pipeline is a LlamaIndex
`FunctionAgent` configured by a *recipe* (system prompt + tool list + output schema +
retrieval/judge policy — see [`RECIPES.md`](RECIPES.md)). RAG *techniques* are not separate
engines; each is a **tool** the agent calls plus **instructions** in the recipe prompt that
say *when and how* to call it. The agent does not improvise the orchestration — the recipe's
tools and prompt dictate it, and adherence is checked afterwards (trace inspection + the
optional judge layer), not enforced by hand-written control flow.

This doc describes the three techniques we package this way, with references, so each can be
(re)implemented as a tool. The design rule for a technique-tool:

> **Package the deterministic core inside the tool; let the agent generate.** A tool
> returns *processed context* (passages, plus any grading/notes), never the final
> answer. Deterministic logic (loops, bounds, scoring rules) lives in code so it is
> reproducible and inspectable; the recipe prompt decides *when* the agent invokes it.
> Tools push retrieved nodes into the shared sink (`harness/tools/search.py:_NODE_SINK`)
> so the runner can rebuild true node-derived citations.

---

## 1. Naive (standard) RAG

**Idea.** Retrieve top-k passages for the query, then generate an answer conditioned on
them. One retrieval, one generation, no self-correction — the baseline. It trusts the
retriever: if retrieval is poor, the answer is poor.

**Reference.** Lewis et al., 2020, *Retrieval-Augmented Generation for Knowledge-Intensive
NLP Tasks*, NeurIPS 2020 (vol. 33, pp. 9459–9474). arXiv:[2005.11401](https://arxiv.org/abs/2005.11401).

**As a tool/instruction here.**
- Tool: **`ema_search`** (`harness/tools/search.py`) — wraps any `BaseRetriever`; optionally
  runs the config-driven pipeline (query-expansion → merge → rerank) when a `transform`/
  `postprocessors` are supplied, else a plain retrieve.
- Recipe: the lightest recipe (`naive_rag`) is the agent given **one tool** (`ema_search`)
  and a prompt that says *call it exactly once, then answer only from the passages*. This
  keeps the simple path cheap and predictable — the right default / benchmark baseline.

> **Try it live:** notebook [`02_steered_retrieval.ipynb`](examples/02_steered_retrieval.ipynb)
> drives the retriever directly, and [`03_routing_and_full_agent.ipynb`](examples/03_routing_and_full_agent.ipynb)
> §2 calls the `ema_search` tool standalone (no LLM) — both headless.

---

## 2. Corrective RAG (CRAG)

**Idea.** Make retrieval *self-correcting*. After retrieving, a lightweight evaluator
**grades** the passages for relevance; if the set doesn't cover the question, take a
corrective action and retry. In the original paper the corrective action is a web search
+ knowledge refinement; generation happens once, after the context is corrected. CRAG is
fundamentally a **retrieval-correction wrapper**, not an answering strategy.

**Reference.** Yan, Gu, Zhu, Ling, 2024, *Corrective Retrieval Augmented Generation*.
arXiv:[2401.15884](https://arxiv.org/abs/2401.15884).

**As a tool/instruction here.**
- Tool: **`corrective_search`** (`harness/tools/corrective_search.py`). It runs the
  deterministic, **bounded** loop *inside the tool*:
  1. retrieve;
  2. **grade** each passage 0/1/2 and list `missing_facts` (rubric in
     `harness/retrieval/corrective.py:GRADE_SYSTEM`);
  3. **sufficient?** = at least one passage scores 2 **and** no missing facts
     (`is_sufficient`);
  4. if not, **rewrite** the query toward the missing facts (`REWRITE_SYSTEM`) and retry,
     up to `max_cycles` (default 2);
  5. return the corrected passages **plus a grade note** that honestly reports residual
     gaps (`grade_note`) — never a final answer.
- No web search (there is no web corpus here); the corrective action is query-rewrite +
  re-retrieve over the Neo4j index. There is no agent-loop risk: the bound and the
  sufficiency rule are code.
- The grading rubric, JSON parser, sufficiency rule, rewrite prompt, and message builders
  are **single-sourced** in `harness/retrieval/corrective.py` (the one definition of the
  CRAG technique).
- Recipe: the `crag_agentic` recipe's toolset includes `corrective_search`, and the prompt
  instructs the agent to *prefer `corrective_search` for multi-hop / scoping questions*
  (the T2/T3 types where a single retrieval underfetches).

---

## 3. ReAct (Reason + Act)

**Idea.** The model interleaves **Thought** (reasoning about what to do next),
**Action** (calling a tool with arguments), and **Observation** (the tool result fed
back), looping until it emits a final answer. The LLM decides which tool to call, with
what arguments, how many times, and when to stop — useful for multi-step / multi-hop
questions.

**Reference.** Yao et al., 2023, *ReAct: Synergizing Reasoning and Acting in Language
Models*, ICLR 2023. arXiv:[2210.03629](https://arxiv.org/abs/2210.03629).

**As a tool/instruction here.** ReAct is not a tool — it *is* the agent loop, which is the
single engine.
- The LlamaIndex **`FunctionAgent`** (built in `harness/agents/regulatory.py`) runs a
  ReAct-style loop using the model's **native tool-calling**, with native structured output
  (`output_cls=RegulatoryAnswer`). The recipe's toolset + prompt define what it can do and
  how it should use the tools; iteration caps bound the loop.
- The `react_agentic` recipe gives it `ema_search` + `resolve_substance` and a reason-act
  prompt; the agent's reasoning/tool-call steps are captured by MLflow autolog so the
  trajectory is inspectable on the trace.

> See also: self-reflective retrieval (Self-RAG, Asai et al., ICLR 2024) generalizes the
> grade/critique idea to learned reflection tokens — a possible future technique-tool.

---

## Adding a new technique as a tool

1. **Implement the deterministic core** as a pure, testable function (e.g. in
   `harness/retrieval/` if it is retrieval-shaped). No LLM/retriever calls inside the pure
   part — pass them in. Keep any loop **bounded**.
2. **Wrap it as a `FunctionTool`** in `harness/tools/` via `@register_tool("name")`. The
   tool returns *processed context as a string* (use `format_nodes`), and pushes nodes into
   `_NODE_SINK` so citations survive. Mirror `corrective_search.py`.
3. **Register** it (import the module in `harness/tools/__init__.py`).
4. **Expose + prescribe it** in a recipe: add the tool name to the recipe's `tools` and
   instruct the agent *when* to use it in the recipe prompt. Do **not** rely on the agent
   discovering the approach on its own.
5. **Make it observable**: ensure the resolved config (which tools, which stages) is stamped
   on the MLflow trace (see [`RECIPES.md`](RECIPES.md) and `harness/obs/config_attrs.py`),
   and verify adherence by inspecting the trace / using the judge layer.

## References

- Lewis et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 33:9459–9474. arXiv:[2005.11401](https://arxiv.org/abs/2005.11401).
- Yan, Gu, Zhu, Ling (2024). *Corrective Retrieval Augmented Generation.* arXiv:[2401.15884](https://arxiv.org/abs/2401.15884).
- Yao et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023. arXiv:[2210.03629](https://arxiv.org/abs/2210.03629).
