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

### What the agent reads in each result

The line under the header is the body, always one line. Since 2026-11-23 it is the
**matched leaf** first — the small chunk the vector search hit — and then its parent
chunk, up to `passage_chars` characters (default 2,000):

```
<matched leaf> || in its section: <parent text before the leaf> [...] <parent text after it>
```

- `passage_chars` is a key of the index profile's `retrieval` block
  (`harness/configs/index/*.yaml`). The value in force is stamped on every trace and
  evaluation run as `ema.retrieval.passage_chars`.
- A node without a separate leaf (no merge, or the leaf is the whole chunk) shows its
  own text, cut to the same limit.
- The leaf's text comes from `metadata['matched_text']`, which the retriever keeps when
  it merges a leaf to its parent (`harness/indexing/property_graph.py`).
- The rendered body is written to the node as `metadata['agent_text']`. The faithfulness
  judge receives exactly this text, so it grades the answer against what the agent read.

Before 2026-11-23 the body was the parent's first 400 characters. On a live
`ema_search` call for "nitrosamine acceptable intake limit" (2026-11-23), the matched leaf
started after character 400 of its parent in 7 of 9 results, so the agent did not see it,
while the judge read the whole parent.

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
  index_profile: neo4j_tree     # which retriever config (see retriever.md); it also sets
                                # passage_chars, the characters of one result body
  routing: default              # optional keyword→category priors
  pipeline: none                # optional query-expansion + rerank pipeline
```

When `retrieval.pipeline` is set, the tool runs the config-driven pipeline
(query transform → multi-query merge → postprocessors/rerank) instead of a bare
`retriever.retrieve()`.

## Observability

- Feeds every node into the shared **sink** (`sink_nodes`) → citations,
  reference cards, and the faithfulness judge's context passages. The judge's passages
  are the rendered bodies (`metadata['agent_text']`, read by `passages_from_nodes`), not
  the full parent text; citations still use the full text.
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
