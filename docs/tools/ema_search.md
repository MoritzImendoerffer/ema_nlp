# `ema_search` — the default retrieval tool

`harness/tools/search.py`. Searches the corpus through
[`HierarchicalPGRetriever`](retriever.md) and returns numbered, source-tagged
passages. Present in nearly every recipe; the *only* tool in `naive_rag`.

## Signature

```python
ema_search(query: str, source_category: str = "") -> str
```

| Argument | Meaning |
|---|---|
| `query` | The search query. The agent formulates this — see *Failure modes*. |
| `source_category` | Optional comma-separated categories to restrict to (`""` = no restriction). |

## What the LLM reads

> Search the EMA human-regulatory corpus (hierarchical retrieval over the Neo4j
> knowledge graph) and return relevant passages with their source URLs and source
> category. Call this before answering any factual question. Optional
> `source_category` restricts the search to one or more categories
> (comma-separated) out of: *…the 13 categories…*. Use it when the results'
> categories do not fit the question — e.g. when a question about general
> requirements keeps returning product-specific documents.

The category vocabulary is injected from `harness/retrieval/doc_categories.py`,
so the prompt can never drift from the code.

## Output format

```
[1] source=https://www.ema.europa.eu/... category=medicine_page score=0.812 path=/medicines/human/EPAR/comirnaty
Comirnaty is a vaccine for preventing COVID-19 …

[2] source=https://www.ema.europa.eu/...pdf category=epar score=0.671 via=link_expansion path=/medicines/human/EPAR/comirnaty
…
```

Per line: source URL, category, score, plus

- `via=<origin>` when the node did not come from plain vector search
  (`link_expansion`, `tree_ancestor`, `topic_subgraph`);
- `path=/<tree_path>` — the document's **level** in the site tree, when the
  [site-tree backfill](site_tree.md) has run.

Both tags exist so the agent can *see* the shape of its evidence — the source-type
mix and where in the hierarchy it sits — and steer a follow-up call.

## Steering precedence

```
explicit source_category  >  routing-table prior  >  profile defaults
```

1. **Explicit argument** — parsed into categories; the retriever is restricted via
   `with_categories()` (hard filter).
2. **Routing table** (`retrieval.routing`, `harness/configs/routing/*.yaml`) —
   first keyword rule that matches the query supplies a prior, in `filter` mode
   (restrict) or `prefer` mode (reorder only).
3. **Profile** — quota / oversample / expansion settings from the index profile.

Every applied step appends a verbatim note (`[routing: …]`,
`[category filter: …]`) to the output *and* to the chain step, so steering is
never invisible.

## Configuration

Recipe side:

```yaml
orchestration:
  tools: [ema_search, resolve_substance]
retrieval:
  index_profile: neo4j_tree     # which retriever config (see retriever.md)
  routing: default              # optional keyword→category priors
  pipeline: none                # optional query-expansion + rerank pipeline
```

When `retrieval.pipeline` is set, the tool runs the config-driven pipeline
(query transform → multi-query merge → postprocessors/rerank) instead of a bare
`retriever.retrieve()`.

## Observability

- Feeds every node into the shared **sink** (`sink_nodes`) → citations,
  reference cards, and the faithfulness judge's context passages.
- Records a `ChainStep` (`record_tool_event`) with args, notes, per-node
  provenance and duration → the chain HTML ([`chain_events.md`](chain_events.md)).
- Runs inside MLflow autolog spans; the nested RETRIEVER span carries full node
  metadata, which is what makes post-hoc chain rebuilds possible.

## Failure modes

- **Empty filtered result** → automatically retries **unfiltered** and notes it,
  rather than returning nothing.
- **Invalid `source_category`** → returns an agent-visible error naming the valid
  categories, and still records a chain step (a rejected steering attempt is part
  of how the run evolved).
- **No results at all** → the literal string `No results found.`
- **Weak seeding on broad questions** — a known, documented limitation: short
  navigational hub pages lose leaf-chunk cosine similarity to long documents that
  repeat a term. See [`../RETRIEVAL.md`](../RETRIEVAL.md) §7.2 ("first live
  result") and the follow-up plan
  [`../next/tree_retrieval_followups.md`](../next/tree_retrieval_followups.md).

## Tests

`tests/test_tools.py` — registry membership, steering precedence, filter +
unfiltered fallback, `format_nodes` rendering of `category` / `via=` / `path=`.
`tests/test_tool_events.py` — the chain step it records.
