# Tools & retrieval reference

One file per agent tool and per retrieval component. This is the **reference**
layer: what each piece does, every knob it exposes, what the LLM sees, what it
stamps for observability, and how to test it. Design rationale lives in
[`../RETRIEVAL.md`](../RETRIEVAL.md); how to compose them into an engine lives
in [`../RECIPES.md`](../RECIPES.md).

There is exactly one engine — a LlamaIndex `FunctionAgent` — and a **recipe**
selects which of these tools it gets (`orchestration.tools`) plus which index
profile feeds them (`retrieval.index_profile`). A RAG "technique" here is a
tool + an instruction, never a separate engine.

## Agent tools

| Tool | File | One line |
|---|---|---|
| `ema_search` | [`ema_search.md`](ema_search.md) | The default retrieval tool: vector search over the graph, optional category steering, link + ancestor expansion. |
| `corrective_search` | [`corrective_search.md`](corrective_search.md) | CRAG: search → grade → rewrite → retry, bounded, best-so-far. |
| `topic_context` | [`topic_context.md`](topic_context.md) | Exhaustive, pageable member list of a curated topic hub (precomputed membership). |
| `resolve_substance` | [`resolve_substance.md`](resolve_substance.md) | Substance name → canonical identity (CAS, synonyms, MW) via PubChem. |

## Retrieval components (below the tools)

| Component | File | One line |
|---|---|---|
| `HierarchicalPGRetriever` | [`retriever.md`](retriever.md) | The retriever every tool calls: chunk vector search + small-to-big + steering + **link/ancestor expansion**. |
| Site tree | [`site_tree.md`](site_tree.md) | Derives the document hierarchy (levels) generically and persists it; powers ancestor context, the KB map, and the chain tree view. |
| Chain capture & export | [`chain_events.md`](chain_events.md) | Records every retrieval-shaped call as a `ChainStep` and renders the per-turn HTML (incl. the site-tree view). |

## How a tool gets wired

```
recipe YAML (orchestration.tools)
  → harness/recipes/build.py::build_recipe
    → harness/tools/registry.py::build_tools(names, retriever=…, router=…, hubs=…, subgraph=…, fetcher=…)
      → each @register_tool builder returns a FunctionTool
        → assembled into the FunctionAgent
```

Every builder receives **all** shared kwargs and ignores what it does not need
(`**_`). To add a tool: write a builder, decorate it with
`@register_tool("name")`, import it in `harness/tools/__init__.py`, and name it
in a recipe. Anything retrieval-shaped must also call `sink_nodes()` (so
citations and the faithfulness judge see its evidence) and `record_tool_event()`
(so the chain export sees it) — see [`chain_events.md`](chain_events.md).

## Conventions every tool doc follows

- **Signature** — exactly what the LLM can call, argument by argument.
- **Tool description** — the text the model actually reads when deciding to call it.
- **Configuration** — recipe/profile keys, with defaults.
- **Output format** — what comes back, including provenance tags.
- **Observability** — what it stamps (`retrieval_origin`, notes, MLflow spans).
- **Failure modes** — what it does when things go wrong, honestly.
- **Tests** — the offline files that pin the behavior.
