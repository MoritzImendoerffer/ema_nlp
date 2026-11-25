---
type: pm-task
epic: 2026-11-23_26_eval-reliability
sprint: 2026-11-23_26_eval-reliability
task: TASK-010
status: done
kind: mechanism
title: "Keep the matched leaf's text on a retrieved node when the retriever merges to the parent"
generated: true
waiting_on: —
tags: [pm/task, pm/done]
---

> [!warning] Generated from `.claude/work/2026-11-23_26_eval-reliability/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-010 — Keep the matched leaf's text on a retrieved node when the retriever merges to the parent

**Epic:** [[epic]] · **Status:** `done` · **Waiting on:** — · **Board:** [[_Board]]

## Why it exists

The defect. `HierarchicalPGRetriever` builds a node in three places: `_retrieve`, `_expand` and `_expand_ancestors` (`harness/indexing/property_graph.py:717-721`, `770-773` and `840-843`). With `merge: true` each takes `parent['text']` and keeps only the leaf's id, as `matched_chunk`. The tool then cuts the parent to its first 400 characters (`harness/tools/search.py:116`), so the agent may never see the leaf that matched. The proposal lists `harness/tools/search.py` only; `exploration.md` section 7.1 found that the leaf's text is gone before the tool sees the node.

The fix is in Python only. The Cypher already returns the leaf's text: `collect({id: c.id, text: c.text, score: score, parent: parent})` in the vector query, and `best.text` in the two expansion queries. Pass it to `_node_from_row` and store it as `metadata['matched_text']`. No graph property changes and no rebuild is needed.

A trap in the installed library. `SentenceTransformerRerank` scores `node.node.get_content(metadata_mode=MetadataMode.EMBED)` (llama-index-core 0.14.22, `llama_index/core/postprocessor/sbert_rerank.py:75`), and this repository builds it for the recipe `agentic_reranked` (`harness/retrieval/postprocessors.py:83-85`). A metadata key is part of that content unless the node excludes it. Put `matched_text` into the node's `excluded_embed_metadata_keys` and `excluded_llm_metadata_keys`, or the reranker scores a passage that holds the leaf twice.

Side effect to record in the outcome: each retriever span in a trace grows by about 500 characters per node (`exploration.md` section 12).

No caller yet: TASK-011 reads `matched_text` in the search tool.

## Acceptance criteria

- [x] `tests/test_indexing_property_graph.py::test_retriever_keeps_the_matched_leaf_text_when_it_merges_to_the_parent` exists and passes: for a row whose leaf text is `LEAF` and whose parent text is `PARENT ... LEAF ...`, the node's `text` is the parent's and `metadata['matched_text']` is the leaf's
- [x] `tests/test_indexing_property_graph.py::test_expansion_and_ancestor_nodes_keep_the_matched_leaf_text` exists and passes: the same holds for a node from link expansion and for a node from the ancestor pass
- [x] `tests/test_indexing_property_graph.py::test_matched_text_stays_out_of_the_reranker_input` exists and passes: `node.get_content(metadata_mode=MetadataMode.EMBED)` and the same call with `MetadataMode.LLM` hold the leaf's text at most once
- [x] `git diff harness/indexing/property_graph.py | grep -c '^[-+].*MATCH '` prints 0: no Cypher query changes
- [x] `tests/test_indexing_property_graph.py` and `tests/test_retrieval_steering.py` pass, including `test_retriever_meta_carries_document_provenance`
- [x] `make test` passes and `make lint` passes, each run on its own line

## What was built

harness/indexing/property_graph.py: _node_from_row takes matched_text and stores it as metadata['matched_text'] when the node's text is the parent's (it is omitted when the node is the leaf itself), with the key in excluded_embed_metadata_keys and excluded_llm_metadata_keys. _retrieve passes r['text'], _expand and _expand_ancestors pass best['text']: the Cypher already returned them, and no MATCH line changed (git diff count 0). 3 new tests (vector node, link-expansion and ancestor nodes, get_content(EMBED/LLM) holds the leaf at most once). tests/test_indexing_property_graph.py and tests/test_retrieval_steering.py pass (38), including test_retriever_meta_carries_document_provenance. Side effect: each retriever span in a trace grows by the leaf's text per merged node, about 500 characters (exploration.md section 12). No graph change, no rebuild. make test: 718 passed, 2 skipped, 7 deselected (exit 0). make lint: All checks passed (exit 0).

## Files it touched

- `harness/indexing/property_graph.py`
- `tests/test_indexing_property_graph.py`
