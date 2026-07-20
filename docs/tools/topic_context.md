# `topic_context` — exhaustive membership of a topic hub

`harness/tools/topic_context.py` + `harness/retrieval/subgraphs.py` (reader) +
`harness/indexing/subgraphs.py` (build side).

Vector search answers "what is *most similar*". Some questions instead need
"what is *all of it*" — every product under a referral, every document in a
procedure family. This tool answers those from a **precomputed membership stamp**,
so completeness does not depend on embedding recall.

## Signature

```python
topic_context(topic: str, query: str = "", page: int = 1) -> str
```

| Argument | Meaning |
|---|---|
| `topic` | Hub key (e.g. `referral_procedures`) or a phrase resolved to one. |
| `query` | Optional — ranks members and selects best passages in `chunks` mode. |
| `page` | 1-based page of the member catalog (`page_size`, default 25). |

## Hubs and subgraphs

A **hub** is a curated topic index page (a seed URL). Its qualified `LINKS_TO`
fan-out defines a **topic subgraph**; membership is computed **offline** and
stamped onto `:Document.topic_hubs`, so query time is a property read, never a
graph walk.

```
seed page ──LINKS_TO*1..h──▶ members     (every node on the path must qualify:
                                          category / doc_type allowed,
                                          audience not excluded)
```

Curation lives in `harness/configs/hubs/*.yaml` (`HubSpec`: seed_url, status,
walk parameters). Build and stamp with `scripts/manage_topic_hubs.py build`
(step `subgraphs` in `scripts/update_graph.py` — deliberately **not** a default
step, since hubs are curated).

## Two context modes

| `context` | Returns |
|---|---|
| `map` (default) | A paged **catalog** of members: title, category, reference number, revision. Complete by construction. |
| `chunks` | The catalog *plus* the best-matching passage of top members, within `max_tokens` (default 4000). |

Members are grouped by their parent detail page (PDFs under the HTML page that
links to them), which is the same linker relationship the
[site tree](site_tree.md) uses.

## Configuration

Recipe (the key is only valid when the tool is in `orchestration.tools` —
enforced at load time):

```yaml
orchestration:
  tools: [ema_search, resolve_substance, topic_context]
retrieval:
  subgraph:
    hubs: default        # configs/hubs/<name>.yaml
    context: map         # map | chunks
    max_tokens: 4000
    page_size: 25
```

Recipe `topic_agent` = `steered_agent` + this tool + the `agent_topic.md` prompt.

## Hub resolution

1. Explicit hub key, if `topic` matches one.
2. Otherwise the memberships of the best-matching document.
3. Multi-membership ties break on which hub's **seed page** best matches the
   query embedding.

## Observability

Nodes (in `chunks` mode) are stamped `retrieval_origin="topic_subgraph"` plus
`topic_hub=<key>`, fed to the shared sink, and recorded as a `ChainStep` — the
chain HTML shows `hub <key>` next to those nodes. A map-only page still records a
step (with zero nodes), because "the agent listed the members" is part of the run.

## Known gaps

- **Curation-gated** — a hub must be built and marked CONFIRMED; without that the
  tool has nothing to resolve.
- **Post-hoc chain rebuilds are lossy** for these nodes: `topic_context` bypasses
  the retriever, so there is no nested RETRIEVER span, and a trace-derived chain
  recovers only what the output line encodes (URL, score, `via`) — not `doc_id`.
  Live exports are complete.
- Membership is only as fresh as the last build; re-run after any `LINKS_TO`
  rebuild, then propagate.

## Evaluation

Live head-to-head on T2 (scoping) items, 2026-07-13: `topic_agent` 5.000/5.000 vs
`steered_agent` 4.700/4.900 — with a documented critique of that comparison's
circularity and statistical power in
[`../eval/2026-07-13_topic_subgraphs.md`](../eval/2026-07-13_topic_subgraphs.md)
§8. Read it as mechanism validation, not generalization.

## Tests

`tests/test_tools_topic_context.py` (grouping, paging, hub resolution,
multi-membership pick, chunk budget, origin stamping),
`tests/test_indexing_subgraphs.py` (the qualified walk),
`tests/test_retrieval_hubs.py` (hub config).
