# Exploration: a pipeline that can refresh the graph

| | |
|---|---|
| Work unit | `2026-11-23_27_pipeline-refresh` |
| Proposal | [`docs/next/pipeline_refresh.md`](../../../docs/next/pipeline_refresh.md) (the requirements; not copied here) |
| Backlog row | 10, top of `Now` |
| Explored | 2026-11-23, by Claude (Fable 5.2) |
| Branch | `pipeline-refresh`, made from `develop` at `9dfc405` |
| Gates before any change | `make test`: 736 passed, 2 skipped, 7 deselected, 18.69 s. `make lint`: "All checks passed!", exit 0 |
| Stores read | MongoDB 8.0.4 (the native `mongod`, `ema_scraper`), Neo4j 5.26.26 community (container `ema_neo4j`). Every query was a read. The two `EXPLAIN` statements in section 5.1 ran in a session with read access and execute nothing |

## 1. Verdict

**The proposal stands.** All five defects are in the code as described, at the lines it
cites. The first was reproduced. Its counts of the graph hold.

Seven points need a correction or an addition before `/plan`. The first is a decision for the
owner: the sketch cannot be built as written without it.

| # | Finding | Consequence | Section |
|---|---|---|---|
| 1 | No parser is named `legacy_pickle`. All 58,121 legacy PDF rows carry `parser: pymupdf4llm`, `parser_version: legacy`. The sketch gives the new byte parser the same name. | Under "preferred parser, then newest `parsed_at`" a new parse replaces the legacy text. That is the opposite of recommendation A(1). **Open question D.** | 3.1 |
| 2 | Open question C rests on a count from another collection. The 26,315 rows are in `parsed_pdfs`. `parsed_documents` records no tool at all. The pickles do: `pymupdf4llm 0.2.9`. | C dissolves. The backfill copies `parser` and `parser_version` from the row, for every document. | 3.2 |
| 3 | Comparing three values re-embeds text that did not change. Today's `parse-html` step reproduces the legacy text on 200 of 200 sampled pages, under a new `parser_version`. | `text_sha256` alone decides whether chunks are replaced. When only the parser or its version differs, the build sets two properties. Otherwise the first pipeline run re-embeds 143,804 HTML leaves for nothing. | 3.3 |
| 4 | `propagate` stays a required step. The join in the build reaches only documents it builds, and it cannot clear a label. | The docs keep `enrich,propagate` as the way to refresh labels. Only the sentence "not needed after a fresh build" becomes true. | 3.4 |
| 5 | `Neo4jPropertyGraphStore.delete` scans all 7.5 million nodes on each call. | The replace step writes its own Cypher from the `:Document` node. | 5.1 |
| 6 | The live check in the proposal's "Verification" parses 20 PDFs and then builds 20 other documents. It writes to both live stores. | It needs one URL through both steps, and it is a `data` task with counts before and after. | 3.6 |
| 7 | The existing test double of the store ignores every query. A test of "no chunk of the first build remains" passes on it whatever the code does. | That test needs a double that models deletion, or a throwaway Neo4j. Neo4j community has one database, and the compose file fixes the container name. | 5.4, 7 |

## 2. The proposal's claims, checked

| Claim | Result | Evidence |
|---|---|---|
| `parse-pdfs` runs `python -m corpus.parsers.pymupdf4llm` | true | `scripts/update_graph.py:119-122` |
| That parser parses no PDF; it calls `pickle.loads` | true | `corpus/parsers/pymupdf4llm.py:100`, `:103` |
| Only `scripts/ingest_parsed_pdfs.py:34` adds the scraper's repository to the path | true | lines 32-34. No other file adds that repository to `sys.path` |
| On a real cache entry the parser returns `pickle_load_failed: No module named 'parsers'` | true, reproduced | entry `ae/ae3551…18ae` of the cache: `error` as quoted, `text` of 0 characters. The pickle names the class `parsers.pdf_parser.PdfDocument` |
| All 58,121 PDF rows carry `parser_version: legacy` | true for the `pymupdf4llm` rows | section 4.1. Five more PDF rows exist (`llamahub_pdf_PDFReader`, `0.6.0`); they are test fixtures |
| `iter_source_rows` reads `find({"error": ""}).sort("url", 1)` and keeps the first row per URL | true | `harness/indexing/ingest.py:178`, `:182` |
| The sort does not say which of two rows comes first; the review found the older one | true | the plan is `FETCH <- IXSCAN url_idx`. Rows of one URL come in the order they were inserted. Nothing guarantees it. For all 5 URLs with two rows the cursor gives the `pymupdf4llm` row first, and the graph holds that row's text |
| `parser_preference.yaml` says that nothing reads it | true | its header, lines 3-9. `grep -rn parser_preference` finds no reader in `harness/`, `corpus/` or `scripts/` |
| A resumed build skips every document that has a chunk | true | `_existing_doc_ids`, `harness/indexing/property_graph.py:233-238`, used at `:304` |
| `:Document` records neither the parser nor a hash | true | `MATCH (d:Document) RETURN count(d.parser), count(d.parser_version), count(d.text_sha256)` gives 0, 0, 0. `IngestedDoc.metadata` already holds `parser` (`ingest.py:115`); `_entity_for` does not write it |
| A chunk's id is `sha256("<doc_id>\|<position>")` | true | `harness/indexing/chunking.py:83-86`, cut to 32 hex characters |
| A shorter text leaves the old chunks with higher positions | true | the store writes with `MERGE … SET` and never deletes (section 5.2) |
| The build calls `build_ingested_doc` without the metadata lookup | true | `property_graph.py:307` |
| Only tests call `ingest()` | true | callers: `tests/test_indexing_ingest.py` only |
| `propagate` is not among the default steps | true | `scripts/update_graph.py:61` |
| `--reset` runs `MATCH (n) DETACH DELETE n` | true | `property_graph.py:453` |
| 7.5 million nodes, 14.6 million relationships, heap 2 GB | true | 7,515,276 and 14,649,381 (section 4.2). `server.memory.heap.max_size` is 2.00 GiB; `dbms.memory.transaction.total.max` is 1.40 GiB |
| The reset also deletes the NeoDash dashboard node | true | one node with the single label `_Neodash_Dashboard` |
| `_delete_links` deletes in batches of 50,000 | true | `property_graph.py:361-364` |
| No test covers any of the five; `update_graph.py` has no test | true | `grep -rln "update_graph\|reset=True\|DETACH DELETE\|prune" tests/` finds nothing. The seed of `test_indexing_ingest.py` holds two clean rows for one URL, and the test asserts only that one survives |
| 79,882 documents lack the three properties | true | section 4.2 |
| `llama-index-core` 0.14.22, `pymupdf4llm` 1.27.2.3 | true | `importlib.metadata`. Also `llama-index-graph-stores-neo4j` 0.7.0, `neo4j` 5.28.4, `pymupdf-layout` 1.27.2.3, `trafilatura` 2.0.0 |
| `tests/fixtures/fixture_pdf_0.pdf` exists | true | 138,034 bytes, starts with `%PDF-1.5` |
| A cache entry is a folder with `meta` and `response_body`; some bodies are gzip | true | files: `meta`, `pickled_meta`, `request_body`, `request_headers`, `response_body`, `response_headers`, and the scraper's `parsed_pdf.pkl`. One "bad magic" entry starts with `1f8b0800` and its header says `Content-Encoding: gzip` |
| The legacy rows came from "another version of an unknown number" | **false** | the pickles record `pymupdf4llm 0.2.9` (section 3.2) |
| "the 26,315 PDF rows whose tool is recorded as `unknown`", "as their row in `parsed_documents` says" | **false as worded** | section 3.2 |
| "the legacy reader keeps the name `legacy_pickle`" | **false** | no file and no row holds that name (section 3.1) |

The 6,760 gzip bodies and the 805 `.pdf-N` files are row 11's counts. One was rechecked
because the cache walker is this item's file: `web_items` holds 805 rows with a PDF content
type whose URL does not end in `.pdf` (`count_documents({content_type: /pdf/, url: {$not:
/\.pdf$/}})`).

## 3. What the proposal got wrong or left out

### 3.1 No parser is named `legacy_pickle` (open question D)

The sketch says: the new parser is named `pymupdf4llm` with the library's version, and "the
legacy reader keeps the name `legacy_pickle`". Open question A then ranks `legacy_pickle`
before `pymupdf4llm`.

The store says otherwise:

```
db.parsed_documents.aggregate([{$group: {_id: {parser, parser_version, kind, clean}, n: {$sum: 1}}}])
  html  trafilatura             legacy   clean  21,957
  pdf   pymupdf4llm             legacy   clean  58,121
  pdf   llamahub_pdf_PDFReader  0.6.0    clean       5
  total                                         80,083
```

A new parse of a legacy PDF would be the row `(url, pymupdf4llm, 1.27.2.3)`. It has the same
parser name as the legacy row and a newer `parsed_at`. The selection rule of the sketch then
picks the new row, whatever the preference file says. The build would replace the text of a
document that was chunked and embedded from the legacy row. Recommendation A(1) exists to
prevent exactly that.

Three ways out. Each keeps the key `(url, parser, parser_version)`.

| Option | What changes | Cost |
|---|---|---|
| D1. A preference entry may name a version: `pymupdf4llm@legacy` before `pymupdf4llm` | the syntax of `parser_preference.yaml` and the selector | no write to a store. The rows keep the key they have had since 2026-05-27 |
| D2. Rename the 58,121 rows to `parser: legacy_pickle` | one `update_many` on `parsed_documents` | a write to 58,121 rows of derived data that no code in this repository can write again (section 4.1). The name describes how the text travelled, not the tool that made it |
| D3. The new parser gets another name | the parser's name | the name `pymupdf4llm` then means "the old text" for good |

*Recommendation: D1.* It writes nothing, and the file then says exactly which rows win. The
backfill stamps `parser: pymupdf4llm`, `parser_version: legacy`, which is what the rows say.
The owner decides; the plan needs the answer before its first task.

### 3.2 Open question C rests on a count from another collection

The 26,315 is a count of `parsed_pdfs`, the older collection, as the review says in its
section 3.2. `parsed_documents` holds no `parsed_with` field: the `meta` of a PDF row has
`cache_path` and `ingested_at` only.

```
db.parsed_pdfs.aggregate([{$group: {_id: {parsed_with, error}, n: {$sum: 1}}}])
  pymupdf4llm 0.2.9   error ""                                38,948
  unknown             error null                              19,494
  unknown             "Invalid PDF (bad magic bytes)"          6,776
  unknown             six other parse errors                      45
  total                                                       65,263
```

Joined by URL (`parsed_pdfs._id` is the URL), the 58,121 `pymupdf4llm` rows of
`parsed_documents` come from 38,729 rows with `pymupdf4llm 0.2.9` and 19,392 rows with
`unknown`. The 6,821 rows with an error never reached `parsed_documents`.

`unknown` is an artefact of the old ingest. The scraper wrote two classes of pickle. The older
class, `parsers.pdf_parser.PdfDocument`, has the field `parsed_with`. The newer class,
`parsers.base.ParsedDocument`, records the tool as `parser_version`, and
`scripts/ingest_parsed_pdfs.py:103` reads `parsed_with` only. Read with `pickletools` (no
unpickling), 60 of 60 sampled `unknown` pickles hold `parser_version: pymupdf4llm 0.2.9`, and
all 150 sampled were of the newer class.

So the legacy tool is known for 38,729 rows and very probably the same for the other 19,392:
`pymupdf4llm` 0.2.9, in layout mode. The backfill needs no special case. It copies `parser` and
`parser_version` from the selected row for all 79,882 documents, and the hash identifies the
text.

### 3.3 Comparing three values re-embeds unchanged text

The sketch: "a document whose three values equal the selected row's is skipped; one that
differs has its chunks and their edges deleted and is built again".

Chunks depend on the text and the chunking settings, not on the parser's name. The check:

```
for 200 rows of db.parsed_documents.aggregate([{$match: {parser: "trafilatura"}}, {$sample: {size: 200}}]):
    TrafilaturaParser().parse(web_items.html_raw, url).text == row.text
  equal text: 200 of 200          (parser version today: trafilatura 2.0.0)
```

`parse-html` is a default step. Its rows would be `(url, trafilatura, 2.0.0)`, newer than the
`legacy` rows, with the same text. Built as sketched, the first pipeline run after delivery
deletes and rebuilds all 21,957 HTML documents: 205,879 chunks and 143,804 embeddings, with no
change in content.

The rule that avoids it: `text_sha256` decides. Hash equal and parser or version different:
set `parser` and `parser_version` on the `:Document`, touch no chunk. Hash different: replace.

### 3.4 `propagate` stays a required step

The sketch says that `propagate` "leaves the docs as a repair step once the build joins".
Two facts limit that.

1. The build joins labels only for documents it builds. An unchanged document is skipped. A
   new export or a hub build changes `document_metadata` without changing any text, and only
   `propagate` carries that to the graph.
2. The build cannot clear a label. `_clean` drops `None` (`property_graph.py:88`), and the
   store writes entities with `SET e += apoc.map.clean(row.properties, [], [])`
   (`llama_index/graph_stores/neo4j/neo4j_property_graph.py:386`). A label that a page lost
   stays on a replaced node. `propagate` sets nulls on purpose
   (`scripts/propagate_metadata_to_graph.py:14-17`).

What the join does repair is the fresh build. Checked read-only: joining `document_metadata`
to the 79,882 graph documents by URL gives `doc_type` on 55,930, `audience` on 20,386,
`site_topic` on 5,947 and `topic_hubs` on 49, with no difference to what the graph holds.
1,995 graph documents, all PDFs, have no metadata row and no label. Those four numbers are
what a build with the join must reproduce.

Three texts state the wrong thing today and belong to this item: the docstring of
`scripts/update_graph.py` (lines 18-20 and 29-31), `docs/RETRIEVAL.md` lines 220-223, and the
docstring of `scripts/propagate_metadata_to_graph.py` (lines 7-9).

### 3.5 A URL whose clean rows all come from an unlisted parser (open question F)

The sketch selects "the first parser that the preference file lists". It does not say what
happens to a URL whose rows all come from a parser the file does not list. No such URL exists
today: the 5 `llamahub_pdf_PDFReader` rows share their URLs with `pymupdf4llm` rows. They are
fixtures (`meta: {synthetic: true, note: "MIGR-015 smoke fixture"}`) that were left in the
live collection.

Two behaviours are possible: skip the URL and count it in the log, or fall back to the newest
clean row with a warning. *Recommendation: fall back with a warning.* A parser that somebody
forgot to list should not remove documents from a build without a trace.

### 3.6 The live check in "Verification" does not test what it says

`python scripts/update_graph.py --steps parse-pdfs,build --limit 20 --pdf-cache <cache>`:

- `parse-pdfs --limit 20` takes the first 20 PDF entries in `os.walk` order of the cache
  (`corpus/parsers/pymupdf4llm.py:161-166`).
- `build --limit 20` takes the first 20 URLs in URL order (`iter_source_rows`).
- The two sets are unrelated. The build would not see the 20 new parses.
- The command writes 20 rows to the live `parsed_documents`. Depending on the answer to D, a
  later build replaces live documents from them.

The parser CLI already has `--url`. The check that proves the path is one URL through both
steps. Under rule 4 of `CLAUDE.md` and the proposal's own last paragraph it is a task of type
`data`, with the document's chunk count before and after.

### 3.7 `--prune` and a narrowed scope

`iter_source_rows` applies `scope.limit` and `scope.topic_prefix`, and `--limit` on the command
line overrides the profile. A prune that compares the graph with the rows of the scope would
delete every document outside the scope: `--prune --limit 200` would remove 79,682 documents.
Prune has to compare with all clean URLs, or refuse to run when the scope is narrowed.

Deleting a `:Document` also deletes its `LINKS_TO` edges. `tree_parent_id` and `topic_hubs` on
other documents then describe a graph that no longer exists, until the steps `tree` and
`subgraphs` run again.

### 3.8 Smaller points for the plan

- **A new text that gives no chunk.** `chunk_document` returns `[]` when the splitter fails
  (`chunking.py:66-78`). If the replace step deletes first and chunks afterwards, a failure
  empties a document. Chunk first; delete only when there are new chunks to write.
- **What the comparison does not cover.** The three values say nothing about `chunk_sizes` or
  the embedding model. A profile with other settings sees "same parse" and skips. That is
  inside the proposal's limit ("it changes no chunking"), and the docs should say it.
- **196 URLs are never in the graph.** They have a clean row and give no chunk (section 4.3).
  They have no `:Document`, so every build tries them again, before and after this work.
- **`LINKS_TO` edges are merged, never removed.** An anchor that left a page keeps its edge
  until `--reset-links`. Links come from `web_items.html_raw`, which changes only with a new
  scrape. Neither row 10 nor row 11 scrapes, so this stays outside both.
- **A selector existed once.** `git show a70c38c:harness/embed_pg.py` holds
  `load_parser_preference` and the hash-skip of the deleted Postgres sync, with
  `tests/test_parser_preference.py`. `DECISIONS.md` ("Three-layer separation", 2026-05-26)
  records the rule that a command-line override replaces the file's list. The proposal
  restores that design on Neo4j.

## 4. The stores today

### 4.1 MongoDB `ema_scraper`

| Collection | Documents | Kind |
|---|---|---|
| `web_items` | 115,101 (22,743 with `html_raw`, 60,650 with a PDF content type) | source |
| `parsed_pdfs` | 65,263 | the older parse store; holds `markdown` |
| `parsed_documents` | 80,083, all with `error: ""` | derived |
| `document_metadata` | 92,630 | derived |
| `link_graph` | 22,743 | unused |

`parsed_documents`: 1,979 MB of data. Indexes: `url_parser_version_uniq` (unique),
`url_idx`, `parser_idx`. Every row has a `parsed_at` of type date, all between 2026-05-27
21:54 and 22:04. No row carries an error, so the parser CLIs of today did not write them:
`corpus/parsers/trafilatura.py` writes an error row for a page under 200 characters.

```
db.parsed_documents.aggregate([{$match: {error: ""}}, {$group: {_id: "$url", n: {$sum: 1}}},
                               {$group: {_id: "$n", urls: {$sum: 1}}}])
  1 clean row: 80,073 URLs      2 clean rows: 5 URLs      distinct URLs: 80,078
```

**No code in this repository can write the legacy rows again.** The version string came from
`corpus/sources/synthetic_legacy_reader.py` (`LEGACY_VERSION = "legacy"`, in git at
`a70c38c`). That file and `scripts/migrate_mongo_to_parsed_documents.py` were deleted in
`7bcf5a5` (LIR-012). `grep -rn '"legacy"' corpus scripts harness` finds nothing today. The
PDF text exists a second time in `parsed_pdfs.markdown`. The plan should treat the legacy rows as data
that is not rebuilt: no step overwrites or deletes them. A new parse cannot overwrite one,
since its `parser_version` gives it another key.

### 4.2 Neo4j

```
MATCH (n) RETURN labels(n), count(*)
  [__Node__, Chunk]                  7,435,393
  [__Node__, __Entity__, Document]      79,882
  [_Neodash_Dashboard]                       1      total 7,515,276
MATCH ()-[r]->() RETURN type(r), count(*)
  HAS_CHUNK 7,435,393   PARENT_OF 7,114,468   LINKS_TO 99,520      total 14,649,381
MATCH (c:Chunk) WHERE c.is_leaf RETURN count(c)                      5,817,230
MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c)        5,817,230
MATCH (c:Chunk) WHERE NOT ()-[:HAS_CHUNK]->(c) RETURN count(c)               0
MATCH (d:Document) RETURN d.source_type, count(*)                    pdf 57,925   html 21,957
MATCH (d:Document)-[:HAS_CHUNK]->(c) RETURN d.source_type, count(c), leaves
  html  205,879 chunks  143,804 leaves      pdf  7,229,514 chunks  5,673,426 leaves
chunks per document: min 3, median 19, 99th percentile 1,300, max 25,916, mean 93
```

Indexes: `ema_chunk_embedding` (vector, `:Chunk(embedding)`), `ema_document_id` (range,
`:Document(id)`), unique constraints on `__Node__(id)` and `__Entity__(id)`, and an unused
vector index `entity` on `__Entity__(embedding)`. **There is no index on `Chunk.doc_id`.**

### 4.3 Do the two stores agree

```
graph URLs: MATCH (d:Document) RETURN d.source_url          79,882
clean URLs: db.parsed_documents.find({error: ""}, {url: 1})  80,078
  in MongoDB and not in the graph: 196      in the graph and not in MongoDB: 0
```

All 196 are PDFs. 195 hold under 200 characters of text. One holds 12,454,382 characters
(`…/rmp-summary/nulojix-epar-risk-management-plan-summary_en.pdf`). The backfill's target is
therefore right: every one of the 79,882 documents has a row to take its three values from.

**The graph was built from the rows that are there now.** For 40 sampled PDF rows and 40
sampled HTML rows, `build_ingested_doc(row, chunking=<neo4j_hier>)` gives exactly the chunk
ids, texts and leaf flags that `MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c)` returns: 80 of
80. Two things follow. The hash of today's row text is the hash of what was embedded. And the
chunker of `llama-index-core` 0.14.22 still gives the ids in the graph, so an unchanged
document keeps its chunks if it is ever built again.

## 5. Deleting from the graph with the installed libraries

### 5.1 `Neo4jPropertyGraphStore.delete` is not usable for the replace step

`llama-index-graph-stores-neo4j` 0.7.0, file
`llama_index/graph_stores/neo4j/neo4j_property_graph.py:738-770`. `delete(ids=…)` runs `MATCH
(n) WHERE n.id IN $ids DETACH DELETE n`, and `delete(properties=…)` runs `MATCH (e) WHERE
e.<key> = $v DETACH DELETE e`. Neither names a label. `PropertyGraphIndex._delete_node` calls
`delete(ids=[node_id])` (`llama_index/core/indices/property_graph/base.py:398`).

The plans, from `EXPLAIN` in a read session (nothing executed):

| Statement | Plan |
|---|---|
| `MATCH (n) WHERE n.id IN $ids DETACH DELETE n` | `DetachDelete <- Filter <- AllNodesScan` |
| `MATCH (e) WHERE e.doc_id = $v DETACH DELETE e` | `DetachDelete <- Filter <- AllNodesScan` |
| `MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c` | `DetachDelete <- Eager <- Filter <- Expand(All) <- NodeIndexSeek` |

The third is the shape to use. It reaches every chunk of a document, at every level, because
every chunk has a `HAS_CHUNK` edge (section 4.2). `DETACH` removes the `PARENT_OF` edges with
the chunks. The `:Document` node stays, and with it `LINKS_TO`, `category`, the `tree_*`
properties and `topic_hubs`.

Whether a deleted chunk leaves the vector index `ema_chunk_embedding` at once is **not
verified**. It needs a real Neo4j and a delete, so it is a task of the plan (section 5.4).

### 5.2 The write order gives crash safety, if the plan keeps it

`upsert_nodes` writes chunks first and entities second (`neo4j_property_graph.py:361-403`),
each with `MERGE … SET`. `_embed_pass` adds a whole document before it checks the flush size,
so one document is never split over two flushes. If the three values live on the `:Document`
and are written by that entity upsert, a crash at any point leaves a document whose values
do not match the selected row, and the next build replaces it again. The plan should state
this as an invariant and test it.

Between the delete and the flush a document has no chunks. The live application can query the
graph in that window. A flush holds about 4,000 chunks.

### 5.3 The batch size for node deletes is unmeasured

`IN TRANSACTIONS OF 50000 ROWS` was verified for relationships, which carry no text and no
vector (`_delete_links`). A `:Chunk` carries its text, and a leaf carries 1,024 floats. The
server allows 1.40 GiB for all transactions together. The biggest document has 25,916 chunks.
The plan should measure the delete on a throwaway instance before it fixes a batch size for
the reset, and should say whether a single document's replace needs batching.

For the reset, every corpus node carries `__Node__`; the dashboard node does not. How long a
batched delete of 7.4 million nodes takes is unknown. It was not run.

### 5.4 A throwaway database is a second container

Neo4j community has one user database. `deploy/neo4j/docker-compose.yml` fixes
`container_name: ema_neo4j` and the volume names, so a second instance needs its own name,
port and volume. The code reads `NEO4J_URI` from the environment (`property_graph.py:72`), so
it can point there. `MONGO_DB` is a constant (`config.py:51`); the tests use `mongomock`.

## 6. The PDF parser

### 6.1 What the scraper's repository does

`~/github_repos/ema_scraper` at `806a4b5` (2026-01-19), with an uncommitted change to
`extract_pdf_text_pymupdf.py` that this exploration did not touch.

- `parsers/pdf_parser.py` imports `pymupdf.layout` before `pymupdf4llm`, calls
  `pymupdf.layout.activate()`, and parses with `pymupdf4llm.to_markdown(doc, pages=None,
  header=True, footer=True)`.
- `extract_pdf_text_pymupdf.py` reads `response_body` and writes `parsed_pdf.pkl` **into the
  cache folder**. This repository treats the cache as source and writes nothing there.
- Neither environment file of the scraper pins `pymupdf4llm`. The version is in the pickles.

### 6.2 The installed `pymupdf4llm` 1.27.2.3, one real call

File `pymupdf4llm/__init__.py`. `to_markdown` goes to `_layout_to_markdown` (lines 57-109)
when `pymupdf.layout` imports, and it does: `pymupdf-layout` 1.27.2.3 is in `.venv`. Without
layout mode the library ignores `header` and `footer` and prints a warning.

Bytes are opened with `pymupdf.open(stream=raw, filetype="pdf")`.

| Input | Result |
|---|---|
| `tests/fixtures/fixture_pdf_0.pdf`, two runs | 11,906 characters each, the same SHA-256, 1.56 s and 1.85 s on the CPU. Stable |
| a cached PDF of 6 pages, 100,485 bytes | 12,924 characters in 1.48 s |
| the legacy row of the same URL | 13,036 characters. Not equal. `difflib` ratio 0.994. The legacy text starts with a picture placeholder that the new text does not have |
| the same PDF without layout mode | 13,390 characters, ratio 0.954 to the legacy text |

So a new parse of a legacy PDF always differs from the legacy text, as the proposal expects.

The library prints to standard output ("=== Document parser messages ===", "OCR on
page.number=0/1"). A CLI that prints its own counts has to expect that.

### 6.3 OCR depends on the machine (open question E)

`use_ocr=True` is the default. On this machine the library chose Tesseract from
`/usr/bin/tesseract`, which is outside `.venv`, and ran it on page 0 of both test files. On a
machine without Tesseract the same PDF gives other text and another hash.

*Recommendation:* the parser passes `use_ocr`, `header` and `footer` explicitly and records
them in the row's `meta`, with the library versions. Keep OCR on, which is closest to how the
legacy text was made. Whether OCR helps is row 17's question. The owner decides.

### 6.4 The cache walker

`_iter_pdf_cache` keeps a URL that ends in `.pdf` (`corpus/parsers/pymupdf4llm.py:129`). The
805 `.pdf-N` URLs fail that test. The proposal gives the gzip case to this item's parser and
the data to row 11. The plan should say the same for the suffix test: which item changes the
walker. `scripts/ingest_parsed_pdfs.py:44-57` holds a copy of the walker.

## 7. Files that change, and the tests

| File | Change | Tests today |
|---|---|---|
| `harness/indexing/ingest.py` | row selection; one function that joins, used by the build and by `ingest()` | `tests/test_indexing_ingest.py`, 7 tests. None asserts which row wins |
| `harness/configs/parser_preference.yaml` | gets a reader; its header changes; its content depends on A and D | none |
| `harness/indexing/property_graph.py` | three properties in `_entity_for`; compare and replace in `_embed_pass`; prune; reset by label in batches | `tests/test_indexing_property_graph.py`, 22 tests |
| `harness/indexing/build.py` | `--prune`; the help text of `--reset` | none |
| `corpus/parsers/pymupdf4llm.py` | parses bytes; the pickle reader moves out of the pipeline | `tests/test_parsers_pymupdf4llm.py`, 13 tests, all on pickles built in the test |
| `scripts/update_graph.py` | the step list and its docstring | none |
| `scripts/ingest_parsed_pdfs.py` | imports `_cli` of the parser (`:29`); its default mode changes meaning when the parser does | none |
| `scripts/propagate_metadata_to_graph.py` | docstring only | `tests/test_document_metadata.py` covers the lookup |
| a backfill script (new) | sets three properties on 79,882 documents | — |
| `docs/RETRIEVAL.md` | the node model (section 3), the step table and the lines 220-223 | — |
| `CLAUDE.md` | the lines on `parse-pdfs` and on the pipeline, where they become untrue | — |

The three test files hold 42 tests and pass in 2.4 s.

**The test doubles cannot show a delete.** `_FakeStore` and `_RecordingStore`
(`tests/test_indexing_property_graph.py:98-162`) record a query and return `[]`.
`test_changed_text_replaces_chunks` and `test_reset_keeps_other_nodes` would pass on them
without any working delete. Rule 10 of `docs/PLANNING_WORKFLOW.md` applies. Either the double
keeps nodes by id and the delete goes through a function it implements, or the two tests run
against the throwaway instance and carry the `integration` mark.

`scripts/backfill_parsed_documents_subset.py:127` writes rows named `pymupdf4llm` from
`parsed_pdfs.markdown`. If D renames anything, this script follows.

## 8. What the work has to preserve

**Source, derived, authored.**

| Place | Kind | What this work does |
|---|---|---|
| Scrapy cache, `web_items` | source | reads `response_body` and `html_raw`. Writes nothing. The new parser does not write into the cache as the scraper did |
| `parsed_documents` | derived | adds rows from the byte parser. Overwrites none. Under D2 only, renames 58,121 |
| `parsed_pdfs` | derived, older | not touched |
| `document_metadata` | derived | read by the join. Not written |
| Neo4j | derived | the backfill sets 3 properties on 79,882 nodes. After delivery a build can delete and rebuild the chunks of a changed document |
| `parser_preference.yaml` | authored | edited by hand in this work. Read by code, written by no tool |
| `benchmark/*.jsonl`, recipes, prompts, hub and routing YAML | authored | not touched |

**The live graph.** The work itself deletes and rebuilds nothing. Two tasks touch the live
graph:

1. The backfill: 79,882 `SET` statements of three properties. No chunk, no vector, no edge
   changes. It reads 1,979 MB of text from MongoDB to hash it. It can stop and resume with
   `WHERE d.text_sha256 IS NULL`. Its duration is not measured.
2. The first live replace, on one document, as a `data` task with counts before and after.

No reset and no full rebuild is part of this item. A full reset stays the owner's decision.

**Comparable numbers.** The work changes no benchmark file, no judge, no runner, no recipe and
no retriever default. The backfill changes no chunk and no edge, so retrieval returns what it
returned before; the counts of `:Chunk` and `LINKS_TO` before and after show it. No earlier
number stops being comparable through this item. Numbers move when row 11 replaces documents.
`DECISIONS.md` ("Earlier evaluation numbers are not repeated before the corpus repair")
already says that nothing is repeated before then.

The system under test gains no path to a gold answer. No touched file reads `corpus.jsonl` or
`benchmark/*.jsonl`, and the build's only text source stays `parsed_documents`.

**Cost.** Paid model calls: 0. GPU: none for the code, the tests and the backfill; one
document's leaves for the first live replace. CPU: about 1.5 s per small PDF, measured on two
files. No embedding rate is recorded in this repository, so the hours of a later mass replace
cannot be estimated from a recorded run; the first replace on real data should measure it. For
scale: all HTML documents hold 143,804 leaves, all PDFs 5,673,426.

**Scope.** No new layer. The item repairs a pipeline that exists, inside Phase 3. It needs
none of the four layers that the decision of 2026-11-23 admits.

**The public repository.** Nothing of the private plan is involved. The URLs quoted here are
public EMA addresses. Paths are written relative to the home directory.

**What it assumes that is not decided.** Open questions A, B, D, E and F below. The plan
cannot fix the selector before D and A are answered.

## 9. What could go wrong

| Risk | Guard |
|---|---|
| A new PDF parse replaces legacy text without anyone asking (finding 1) | answer D before the selector is written; `test_preferred_parser_row_wins` uses the real names and versions of the store |
| The first pipeline run re-embeds all HTML (finding 3) | the hash decides; a test with two rows of equal text and different versions asserts that nothing is embedded |
| `--prune` with a narrowed scope deletes most of the graph (3.7) | compare with all clean URLs or refuse; a test with `limit` set |
| A failed chunking empties a document (3.8) | chunk before delete; a test with a text that gives no chunk |
| A delete that works on a fake and not on Neo4j (finding 7) | one real run on a throwaway instance before the first live one |
| A batch of chunk deletes exceeds the transaction memory (5.3) | measure on the throwaway instance; the reset is not run on the live graph in this item |
| The backfill stamps a hash that is not the embedded text | checked on 80 of 80 documents (4.3); the backfill can repeat the check on a sample and print the result |
| The live check changes live documents (finding 6) | one URL, a `data` task, the owner's yes before it runs |

## 10. Open questions

| | Question | Recommendation | Who |
|---|---|---|---|
| A | Which PDF parse does the preference file name first? (proposal) | the legacy rows first, as the proposal recommends. It only has an effect once D is answered | owner |
| B | Is a removed URL deleted from the graph? (proposal) | keep by default, `--prune` on request, as the proposal recommends. Today 0 graph documents lack a row, so nothing would be pruned | owner |
| C | What does the backfill write for the `unknown` rows? (proposal) | **dissolved** (3.2): it copies the row's `parser` and `parser_version` | — |
| D | How are the legacy PDF rows and the new parser told apart? (3.1) | D1: a preference entry may name a version, `pymupdf4llm@legacy` | owner |
| E | Does the byte parser run OCR, which uses the system's Tesseract? (6.3) | keep it on, pass the options explicitly, record them in `meta` | owner |
| F | What does selection do with a URL whose rows all come from an unlisted parser? (3.5) | fall back to the newest clean row, with a warning and a count | owner |

Not answered from the code or the stores, and left to a task of the plan:

- whether a deleted chunk leaves the vector index at once (5.1);
- the batch size for node deletes and the duration of a batched reset (5.3);
- the duration of the backfill, and the embedding rate of a replace.

## 11. Found on the way, not this item's

These belong to backlog row 12 (docs). They are listed here so that they are not lost; this
command changes no file for them.

- `CLAUDE.md` names `corpus/sources/synthetic_legacy_reader.py`. The file was deleted in
  LIR-012.
- `CLAUDE.md` says MongoDB must run as the pinned container. The native `mongod` 8.0.4 is the
  one that runs, on port 27017.
- The container `ema_nlp_pg` (`pgvector/pgvector:pg16`) still runs. Nothing in the repository
  uses Postgres since LIR-012.
- 5 fixture rows (`llamahub_pdf_PDFReader`, `meta.synthetic: true`) sit in the live
  `parsed_documents`.
