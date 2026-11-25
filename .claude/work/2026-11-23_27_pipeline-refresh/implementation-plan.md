# Implementation plan: a pipeline that can refresh the graph

| | |
|---|---|
| Work unit | `2026-11-23_27_pipeline-refresh` |
| Proposal | [`docs/next/pipeline_refresh.md`](../../../docs/next/pipeline_refresh.md), the requirements |
| Exploration | [`exploration.md`](exploration.md), the code and the stores as they are |
| Tasks | [`state.json`](state.json), 18 tasks; the board is `docs/pm/_Board.md` (`make pm`) |
| Planned | 2026-11-25, by Claude (Opus 5.5) |
| Decisions A, B, D, E, F | taken on 2026-11-25 by the lead assistant session under the owner's delegation; the owner can overrule each (`docs/pm/decisions/2026-11-25_*.md`) |
| Open | G, the pickle reader (blocks TASK-010); the go-ahead for the two live runs (TASK-015 writes it) |

## What is built

`scripts/update_graph.py` can add a document that is new and cannot change one that exists. After
this work a document in the graph records which parse it was built from: `parser`,
`parser_version` and `text_sha256` on its `:Document` node. For each URL the build picks one
row of `parsed_documents`: the first entry of `parser_preference.yaml` that matches, then the
newest `parsed_at`. It then compares that row with what the graph records:

| Graph | Selected row | Action |
|---|---|---|
| no document with chunks | any | build it |
| same hash, same parser and version | | skip |
| same hash, other parser or version | | set the two properties, touch no chunk |
| other hash | | chunk the new text; delete the old chunks; write the new ones |
| no recorded values (before the backfill) | | compare with the row the old rule picked |

The PDF step parses `response_body` bytes with the `pymupdf4llm` in `.venv`. The real build joins
`document_metadata`. `--prune` deletes documents whose URL has no clean row any more. `--reset`
deletes `:Chunk` and `:Document` nodes in batches and keeps the NeoDash dashboard node.

## The order, and why

1. **Selection and the stored shape first** (TASK-001 to TASK-004). They are small and pure. Every
   later task depends on them, and none of them touches a delete.
2. **The deletes behind one seam** (TASK-005). The test doubles of today ignore every query
   (`tests/test_indexing_property_graph.py:98-162`), so a delete test on them proves nothing.
   The build therefore talks to named operations: a test double implements them on dicts, and a
   real Neo4j runs the Cypher (TASK-013).
3. **The comparison** (TASK-006), then prune and reset (TASK-007, TASK-008), all on that seam.
4. **The PDF parser** (TASK-009) can be done in parallel. Its wiring (TASK-010) waits for
   decision G.
5. **The command-line flags and the backfill script** (TASK-011, TASK-012).
6. **A throwaway Neo4j** (TASK-013) runs the Cypher for real and measures what the exploration
   left open: does a deleted chunk leave the vector index at once, can one document of 26,000
   chunks be deleted in one transaction, and how long does a batched reset take. TASK-014 fixes
   the batch sizes from it.
7. **The docs** (TASK-018), then **the checkpoint** (TASK-015). The checkpoint measures the
   backfill's duration with a read-only dry run and asks for the two live runs.
8. **The live runs** (TASK-016 backfill, TASK-017 one URL) wait for the owner's yes.

Critical path: TASK-001 → 002 → 006 → 013 → 014 → 015 → 016 → 017.

## Choices the plan made

These are the plan's own choices, not decisions of the owner or the lead. Each can be overruled.

- **Prune compares with all clean URLs**, never with the scope (exploration 3.7).
- **A graph document without the three values** is compared with the old-rule row, as the
  proposal says. That row is the first clean row the cursor yields for the URL. The build does
  not stamp such a document when the rows agree; the backfill does.
- **`--no-resume` replaces every document** (delete, then rebuild). Today it re-MERGEs without
  deleting, which leaves stale chunks when a text got shorter.
- **The `.pdf-N` suffix test of the cache walker** stays as it is. Changing it is row 11's work,
  together with the 805 files it would find.
- **The old chunks are deleted inside the flush**, just before the new ones are written, to keep
  the window without chunks short (a flush holds about 4,000 chunks).
- **CLAUDE.md is not edited in this unit's tasks.** Its lines on `parse-pdfs` become untrue; they
  are left for `/ship`, with the owner present.

## What could go wrong

| Risk | Guard |
|---|---|
| A new PDF parse replaces legacy text without anyone asking | decisions A and D; `test_preferred_parser_row_wins` uses the store's real names and versions |
| The first pipeline run re-embeds all 143,804 HTML leaves | the hash decides; `test_equal_text_new_version_stamps_only` |
| `--prune` with a narrowed scope deletes most of the graph | compare with all clean URLs; `test_prune_ignores_scope_limit` |
| A failed chunking empties a document | chunk first, delete afterwards; `test_text_without_chunks_keeps_old_chunks` |
| A delete that works on the double and not on Neo4j | TASK-013 runs the Cypher on a throwaway Neo4j before any live run |
| A batch of chunk deletes exceeds the 1.40 GiB transaction memory | measured in TASK-013; the batch sizes come from that page |
| A test writes to the live graph | the scratch tests refuse a URI with port 7687, and skip without `EMA_SCRATCH_NEO4J_URI` |
| The byte parser and a pickle reader write the same key | decision G before TASK-010 |

## What is not attempted

- No content repair: the HTML extractor, the gzip PDFs and the `.pdf-N` files are row 11.
- No chunking change and no new chunk ids: rows 13 and 17.
- No reset and no full rebuild of the live graph.
- No paid model call and no GPU job longer than one hour. The one-URL run embeds one document.
- No command-line override of the preference file: the proposal does not ask for one.
