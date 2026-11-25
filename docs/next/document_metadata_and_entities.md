# Document metadata and a medicines table from EMA's own feeds

**Status:** proposed 2026-11-25 · backlog row 13 · no work unit yet · waits for rows 10 and 11

Written from the review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md),
sections 3.3 and 6) and the direction review of 2026-11-25
([`../eval/2026-11-25_direction_review.md`](../eval/2026-11-25_direction_review.md), sections 5
and 6). Every count in the column "Found" below comes from a read-only query on the live MongoDB
and Neo4j on 2026-11-25. The code was read at `0de00d7`, while unit 27 was changing it.
`/explore` checks all of it again.

Four terms. A *feed* is one of the JSON files that EMA publishes as "website data". The
*product number* is EMA's identifier of a centrally authorised medicine, for example
`EMEA/H/C/000481`. The *INN* is the international non-proprietary name of a substance, for
example adalimumab. A *file card* is the box on an EMA page that links one document and shows
its status, reference number and dates.

## The problem

The graph knows a document by its URL and its text. It does not know which medicine the
document belongs to, when it was published, or whether it is adopted or a draft. Three kinds of
question fail for that reason.

1. **A question about one product.** "Which variation reports exist for Humira?" EMA's
   documents feed assigns 57 PDFs of the graph to product `EMEA/H/C/000481`, 44 of them
   variation reports. The graph cannot name them: `:Document` has no product property, and the
   search tool has one filter, the source category (`harness/tools/search.py:223`). The title
   does not help. 42,584 of 57,925 PDFs (73.5%) carry their URL slug as title. One of the 57 is
   titled "humira h c 481 ii 0088 epar assessment report variation en". The feed calls it
   "Humira-H-C-481-II-0088 : EPAR - Assessment Report - Variation".
2. **A question about a version.** By EMA's feed the graph holds 879 adopted and 912 draft
   scientific-guideline PDFs. No property tells them apart, and no document carries a date. A
   check such as "the cited document is the current version" (direction review, section 5) has
   nothing to read.
3. **A question about all medicines with a property.** "How many medicines does EMA list as
   biosimilars?" The medicines feed answers with one count: 181. The graph has no table to
   count in. Backlog row 15 needs such computed answers for the classes C5, C6 and C8, and the
   check "this count equals the count computed from the table" needs the table.

The product is also the "project" of the experiment ladder: rung E1 loads one product's
documents, and the benchmark holds one product out. Without the product number that unit does
not exist.

| Checked on 2026-11-25 | Review of 2026-11-23 | Found |
|---|---|---|
| Where the feeds are | 15 in `web_items`, 11 cached on disk | 15 rows in `web_items`, each a URL and a content type, without a body. All 15 bodies are in the Scrapy cache `cache/ema-sitemap` (fetched 2025-12-31 and 2026-01-01; one is an empty list). 11 of them are also in `cache/ema-json-spider` (2025-12-28) |
| Documents feed with product numbers | 69,887 records | 69,887, in `.tmp/ema_documents_export.json`, downloaded 2026-07-13, outside both caches. Keys: `id`, `name`, `type`, `status`, `consultation_date`, `first_published_date`, `last_updated_date`, `reference_number`, `medicine_name`, `ema_product_number`, `document_url`. The cached copy of 2025-12-28 has 67,622 records, other key names (`url`, `publish_date`) and no product number |
| Medicines feed | 2,649 medicines, 2,271 human | 2,649 records, 39 keys, the product number unique. 2,271 `Human`, 378 `Veterinary`. Relied on: `ema_product_number`, `name_of_medicine`, `international_non_proprietary_name_common_name`, `active_substance`, `atc_code_human`, `pharmacotherapeutic_group_human`, `therapeutic_area_mesh`, `medicine_status`, `revision_number`, `medicine_url`, and 9 date keys |
| `document_metadata` | all HTML pages, 96.6% of PDFs | 92,630 rows. `url`, `doc_id` and `provenance` on all; `doc_type` on 69,887; `audience` and `site_topic` on 22,743; `topic_hubs` on 49. They cover 77,887 of 79,882 graph documents (97.5%): 21,957 of 21,957 HTML pages and 55,930 of 57,925 PDFs |
| `:Document` properties | no date, status or product | 17 keys. On all 79,882: `id`, `name`, `source_url`, `source_type`, `title`, `category`, `topic_path` and four `tree_*` keys. `doc_type` on 55,930, `audience` 20,386, `reference_number` 12,629, `committee` 10,145, `site_topic` 5,947, `topic_hubs` 49 |
| `:Chunk` properties | six, none for position | `id`, `text`, `is_leaf`, `doc_id`, `source_url`, `embedding` on the first 200,000 of 7,435,393 chunks. `CALL db.propertyKeys()` lists no key for order, page or section in the whole database |
| Graph PDFs that join the documents feed by URL | 55,930 | 55,930. Status: 20,054 `Adopted`, 2,703 draft, 33,173 `unknown`. 12,072 were updated after first publication |
| Of these, with a product number | 13,667 in 2,137 products, median 6 | The same. 1,878 products are human, 259 veterinary |
| Products that join the medicines feed | 2,130 | 2,130 as stored. 2,135 once five values lose their trailing spaces. The other 2 products, with 10 PDFs, are not in the medicines feed cached on 2025-12-28 |
| Medicine pages in the graph | 2,640 of 2,649 | The same. So 16,307 graph documents name a medicine: 13,667 PDFs by product number, 2,640 pages by URL |
| Reference numbers | 43,316 in the feed, 36,635 on joined PDFs, 12,629 in the graph, 86% equal | 44,107 in the feed (791 more), 36,635, 12,629, and 10,300 of 11,950 equal (86%) |
| Distinct INNs of human medicines | 1,252 | 1,251 |

**A limit of the feed.** Its `status` has five values: `Adopted`, `Draft`, `Draft: consultation
closed`, `Draft: consultation open` and `unknown`. None says superseded or withdrawn. Example:
the feed says `Adopted` for "Appendix 2 to the Guideline on the evaluation of Anticancer
Medicinal Products in Man (CPMP/EWP/205/95 Rev. 3)", and the guideline's page lists the same PDF
under the heading "Superseded document - Appendix 2". Whether a medicine is withdrawn is a field
of the medicines feed (391 `Withdrawn`), not of a document.

Not re-checked, from the review of 2026-11-23: the 301 guideline families with several versions,
the count of 18 feeds, the scientific-guidelines feed added on 2026-10-08, and both licence
statements.

## The idea

Carry EMA's own tables into the stores through the seam that backlog row 10 opens. Mongo
`document_metadata` holds one row per URL, the build joins that row onto `:Document`, and
`scripts/propagate_metadata_to_graph.py` patches the documents that already exist. Stage 1 adds
one group of fields from the documents feed (title, status, two dates, reference number,
product number) and one new collection, `medicines`, with one row per product number. A
document joins its medicine by the product number. Stage 2 derives further tables from the
feeds, gives chunks their order, section and page, and gives file-card edges a version role. No
value is extracted by a model. Every value is a field of an EMA table or of an EMA page, so the
layer rebuilds in minutes and embeds nothing.

## What it deliberately does not do

- **No LLM extraction.** `harness/ontology/enrich.py` stays as it is, for rung E8.
- **No re-embedding.** No chunk changes its text, its boundaries or its id.
- **No use of the new values.** No search filter, no read tool, no steering, no change to what
  a retrieved passage carries. Those are rows 14 and 18 and the parked row "Metadata steering".
- **Stage 1 does not say "superseded" or "withdrawn" about a document.** The feed has no such
  value. Stage 2 reads the page headings.
- **No `:Medicine` nodes in Stage 1** (open question 1) and no table of organisations. The
  holder stays a field of the medicine's row.
- **No completeness check of the crawl against the feed.** That is row 11.
- **No removal of veterinary content.** The graph holds 3,829 documents of that category.
- **No text from the WHO ATC index** (open question 5).
- **No write to `web_items` or to the Scrapy cache.** A downloaded feed is a new, dated file.
- **No consultation date** (1,423 joined rows), and no feed beyond the nine named in this
  file. The scientific-guidelines feed of 2026-10-08 is not on disk.

## Implementation sketch

Size: M. Stage 1 is one or two sessions. Stage 2 is a few, and starts when Stage 1 is verified.
Stage 1 needs row 10, which makes the real build join `document_metadata`. The chunk
properties of Stage 2 need row 11, which changes the text that is chunked.

### Stage 1: what rows 14, 15 and the answer checks need first

| # | Change | Where |
|---|---|---|
| 1 | Read every field of a feed record, not two. `json.loads` per record works for 69,857 of 69,887. The other 30 have unescaped quotes in `name` and need the existing regex route. `parse_document_types_by_url` stays as a wrapper. A missing key stops the run and is named | `harness/indexing/doc_types.py:37-60` |
| 2 | A field group `feed` on the `document_metadata` row, written like the groups of today: field-scoped `$set`, own provenance. The existing document-type pass writes it from the same read of the file | `harness/indexing/document_metadata.py`, `scripts/enrich_document_metadata.py` |
| 3 | The medicines table, as one new pass: read the medicines feed (downloaded when absent, like the export), write one row per product number, and stamp `product_number` with `provenance.medicine` on the `document_metadata` row of each `medicine_url` | new `harness/indexing/medicines.py`; the pass list at `scripts/enrich_document_metadata.py:158` |
| 4 | The build join carries the group. `build_ingested_doc` copies it into `metadata`, and `_entity_for` writes it. The feed's name becomes the title where there is one. The `last_updated` that ingest derives from the text at line 122, and that no code writes to the node, gives way to the feed's value. No feed value enters `base_meta` | `harness/indexing/ingest.py:114-145`, `harness/indexing/property_graph.py:182` |
| 5 | The patch of the existing graph: `propagate` sets the group on every document whose row has `provenance.feed`, sets `product_number` where the row has `provenance.medicine`, and creates a range index on `:Document(product_number)` | `scripts/propagate_metadata_to_graph.py:58-108` |
| 6 | The node model and the data flow in the docs | `docs/RETRIEVAL.md` sections 2, 3 and 7 |

Stored shapes:

- **`document_metadata` row** gains `title`, `status` (EMA's string, `unknown` included, so that
  a missing value means "not in the feed"), `first_published`, `last_updated` (ISO 8601 as in the
  feed), `reference_number`, `product_number` (stripped of spaces) and `provenance.feed` with
  the source, the write time and the feed's own timestamp. An empty value is stored as null.
- **`medicines` row:** `_id` is the product number. The 39 keys of the feed are kept as they
  are, with the dates converted from `DD/MM/YYYY` to `YYYY-MM-DD` so that they sort. Added:
  `doc_id` (the hash of `medicine_url`) and `provenance`. 2,649 rows.
- **`:Document`** gains `status`, `first_published`, `last_updated` and `product_number`.
  `title` and `reference_number` take the feed's value where the feed has one.
- **The join** is `:Document.product_number` = `medicines._id`. Stage 1 creates no edge.

**Nodes or a collection for the medicines table.**

| | `:Medicine` nodes and edges to `:Document` | Mongo collection, product number on `:Document` |
|---|---|---|
| The seam of row 10 | A second pass after the build, like the link pass | A field of the row that the build joins |
| After a reset, or when a document is replaced | The reset deletes `:Document` and `:Chunk` only (`reset_corpus`, `harness/indexing/graph_ops.py`). The nodes stay, and every edge is gone until the pass runs again | The build writes the property itself |
| Readable without Neo4j: rungs E1 and E2, the computed answers of row 15 | No | Yes |
| From a medicine to its chunks in one query (rung E8) | Yes | Two steps: product numbers from Mongo, then `WHERE d.product_number IN $list` on the index |

Recommendation: the collection. Three of four lines favour it, and the fourth concerns a rung
that is not open. When E8 opens, nodes can be projected from the collection in minutes.

### Stage 2: the rest of the review's sections 3.3 and 6

| Part | Source | Size, checked 2026-11-25 | Written to |
|---|---|---|---|
| Substances | `active_substance` and the INN of each medicine row | 1,251 INNs and 1,382 substance strings on 2,271 human medicines; 161 INNs have 3 or more products | collection `substances` |
| ATC classes. The ATC code classifies a medicine in five levels that the code spells out: `L04AB04` lies in `L`, `L04`, `L04A` and `L04AB` | `atc_code_human`, `pharmacotherapeutic_group_human` | 1,093 distinct code strings, 952 of them full codes of 7 characters. Their prefixes give 14, 75, 138 and 314 classes at levels 1 to 4. 264 group names | collection `atc_classes` |
| Therapeutic areas | `therapeutic_area_mesh`, split at `;` | 652 terms, 3,831 medicine-term pairs | collection `therapeutic_areas` |
| Procedures | seven feeds: referrals 589, safety update assessments 2,515, orphan designations 3,138, paediatric plans 3,248, safety communications 160, shortages 74, post-authorisation 131. Relied on: the page URL key of each (`referral_url`, `psusa_url`, `orphan_designation_url`, `pip_url`, `dhpc_url`, `shortage_url`, `medicine_url`) | 9,855 records. The page of 9,802 of them is a graph document | collection `procedures`; `procedure_kind` on the page's row |
| Chunk order and section | the chunker; the nearest heading above the chunk | 7,435,393 chunks. 250 of 300 sampled PDF texts hold a markdown heading | `position`, `level`, `section` on `:Chunk` |
| Chunk page | a parse that records page ends | 0 of 300 sampled PDF texts hold a page mark (open question 6) | `page` on `:Chunk` |
| Version role of a file card | the heading above the card, and the card's own fields, in `web_items.html_raw` | 54,347 file-card edges. On the 818 pages whose URL ends in `scientific-guideline`: 2,872 cards, 2,845 with a reference number, 924 with a legal effective date | `card_heading`, `version_role`, card fields on `LINKS_TO` |
| Dates of HTML pages | `article:published_time`, `article:modified_time` | 957 and 672 of 1,000 sampled pages | `first_published`, `last_updated` on the page's row |

**Licence.** Stage 2 stores the ATC code as EMA's medicines feed gives it, reads the levels from
the code, and uses EMA's own `pharmacotherapeutic_group_human` text as the only label. It copies
nothing from the WHO ATC index, which forbids commercial redistribution and modification. EMA
allows reuse of its data with attribution. Both licence statements are from the review of
2026-11-23, not re-checked.

### What each stage costs

| | Stage 1 | Stage 2 |
|---|---|---|
| Mongo rows written | At most 72,536 in `document_metadata` (69,887 feed records, 2,649 medicine pages) and 2,649 in `medicines` | About 13,000 in four collections |
| Graph elements written | `SET` on 58,570 of 79,882 `:Document` nodes (55,930 PDFs, 2,640 medicine pages); one index | `SET` on 7,435,393 `:Chunk` nodes; 99,520 `LINKS_TO` edges deleted and merged again by the existing `--links-only --reset-links` |
| Chunks re-embedded | 0 | 0 |
| Live graph | Patched in place, no rebuild | Patched in place, no rebuild |
| Duration | Not measured. `propagate --dry-run` reports the join before any write | Chunking again runs at 1,710 chunks per second on one core (120 random documents): about 1.2 hours for all. The Neo4j write time is not measured |

Why nothing is re-embedded, read in the code. The build embeds `c.text`, the chunk's text alone
(`harness/indexing/property_graph.py:376`). It decides to rebuild a document from three values
only: `parser`, `parser_version` and `text_sha256` (`_decide`, line 272). A changed metadata row
gives `skip`. One risk: `source_type` and `reference_number` in `base_meta` count against the
chunk size (`harness/indexing/ingest.py:140`, `harness/indexing/chunking.py:29`). A feed value
that entered `base_meta` would move chunk boundaries and ids at the next rebuild. The title is
excluded there, so the feed's title is safe. Chunking 40 random documents again on 2026-11-25
reproduced the graph's chunk ids for all 40.

## Verification

**Tests**, in `tests/test_doc_types.py`, `tests/test_document_metadata.py`,
`tests/test_indexing_ingest.py` and a new `tests/test_medicines.py`:

- `test_feed_record_with_unescaped_quote_keeps_all_fields`
- `test_feed_without_product_number_key_stops`: the key names of 2025-12-28 raise, and the
  message names the missing key.
- `test_product_number_is_stripped`
- `test_feed_group_keeps_badges_and_doc_type`
- `test_one_medicine_row_per_product_number`, `test_medicine_dates_sort`,
  `test_medicine_page_row_gets_product_number`
- `test_build_joins_feed_fields`: the function that the real build calls returns a document
  with `status`, both dates, `product_number` and the feed's title.
- `test_feed_fields_do_not_move_chunk_ids`: one text, with and without a metadata row, gives
  the same chunk ids.
- `test_changed_metadata_row_is_skipped`: on `tests/graph_double.py`, a second build after a
  changed row embeds nothing.
- `test_propagate_sets_feed_group_and_no_chunk`

**Reachability.** `python scripts/update_graph.py --steps enrich,propagate --dry-run` prints
both commands, and `grep` shows the medicines pass called from `main()` of the enrich script.

**Read-only queries after Stage 1.** The numbers hold for the two files on disk today. A new
download changes them, and the session records the new numbers with the download's timestamp.

| Query | Expected |
|---|---|
| `document_metadata.count_documents({"provenance.feed": {"$exists": true}})` | 69,887 |
| `document_metadata.count_documents({"product_number": {"$type": "string"}})` | 22,853 (20,204 feed records and 2,649 medicine pages) |
| `medicines.count_documents({})`, then with `{"category": "Human"}`, then `{"biosimilar": "Yes"}` | 2,649, 2,271, 181 |
| `MATCH (d:Document) WHERE d.status IS NOT NULL RETURN count(d)` | 55,930 |
| `MATCH (d:Document {status: 'Adopted'}) RETURN count(d)` | 20,054 |
| `MATCH (d:Document) WHERE d.product_number IS NOT NULL RETURN d.source_type, count(d)` | pdf 13,667, html 2,640 |
| `MATCH (d:Document) RETURN count(DISTINCT d.product_number)` | 2,642 |
| `MATCH (d:Document {product_number: 'EMEA/H/C/000481'}) RETURN d.source_type, count(d)` | pdf 57, html 1 |
| `MATCH (c:Chunk) RETURN count(c)`; the same `WHERE c.is_leaf`; `MATCH ()-[r:LINKS_TO]->() RETURN count(r)` | 7,435,393, 5,817,230 and 99,520, before and after |

The number of PDFs whose title equals the URL slug falls from 42,584 to at most 2,023.

**What would stop the row.** A downloaded feed without `ema_product_number` or `document_url`.
Fewer than 55,930 graph PDFs joining by URL. Any change in the three counts of the last line.

## Open questions

"Owner" marks a question that the owner must answer. "Lead" marks one that the lead assistant
session may answer under the owner's delegation of 2026-11-25, and that the owner can overrule.

| | Question | Options | Recommendation | Who |
|---|---|---|---|---|
| 1 | Medicines as nodes or as a collection? | (a) `:Medicine` nodes and edges, the shape the review suggests; (b) a collection and a property | (b), see the comparison above | Owner: it departs from the review |
| 2 | Which copy of the feeds? | (a) the files on disk: documents of 2026-07-13, medicines of 2025-12-28, with 2 of 2,137 products not joining; (b) download both on one day | (b). Keep each download as a dated file that no tool overwrites, and record its timestamp. EMA renamed keys between the two dates, so check the keys first | Lead |
| 3 | Which reference number where feed and text differ (1,650 documents)? | (a) the feed's; (b) the text's; (c) both | (a). In 12 sampled pairs the feed held the same number in another form (prefix, committee part, revision suffix) 8 times, and another number 4 times. The text's value stays in chunking | Lead |
| 4 | Veterinary rows: 378 medicines, 259 products with 1,352 graph PDFs | (a) load all, keep EMA's `category`; (b) human only | (a). The documents are in the graph, and a table with fewer products than the documents name would fail the join check | Owner: it touches the scope lock |
| 5 | ATC labels and their licence | (a) the code as EMA's feed gives it, levels read from the code, EMA's own group name as the only label; (b) add level names from the European Commission's Union Register (CC BY 4.0), a new download; (c) no ATC | (a) in Stage 2, (b) when a question of rung E4 needs a level name. The repository commits no feed data. A benchmark item of row 15 would be the first place a code is published | Owner |
| 6 | The page of a chunk for the 58,121 PDFs parsed before row 10 | (a) only where a row of the byte parser exists, which is the 7,565 PDFs of row 11; (b) parse all again and re-embed what changed, a GPU job of the size of the first build (15 hours by the review, not re-checked); (c) read the other repository's pickles | (a). Decide (b) together with row 17 | Owner for (b) |
| 7 | How does a card heading become a version role? Headings are free text. A rule on three words sorts the 2,872 cards into 1,297 current, 86 superseded, 1,438 history and 51 other | (a) store the heading only; (b) also a `version_role` from a hand-written pattern file; (c) also copy the role to the target document | (b). (c) only after the 1,438 history cards were read: one PDF can sit under two headings on two pages | Lead |
| 8 | Procedures that name a medicine without its number | The product number is filled in 277 of 3,138 orphan designations (253 join) and in all 131 post-authorisation records. Referrals name a centrally authorised medicine in 45 of 589 records; the safety update feed in none. (a) join on product number and page URL only; (b) also on an exact name | (a). A name match is a guess, not a field of an EMA table | Lead |
| 9 | Product by link: a medicine page links 18,781 PDFs through file cards, and 5,334 of them have no product number in the feed | (a) the feed only; (b) a second property from the link | (a). Where both exist they agree for 12,976 PDFs and differ for 471. Read those before (b) | Lead |

Not a question of this row, and stated so that nobody waits for it: decision B of row 10
(whether a removed URL leaves the graph) was deferred until "the document status of row 13".
Stage 1 cannot settle it, because the feed has no value for a withdrawn document.

## For the implementing session

- Check every count and every line reference above. Unit 27 is changing `harness/indexing/` and
  `scripts/`, and row 11 will change the text of about 22,700 HTML pages and add 7,565 PDFs.
- Read the keys of the file before you parse it. A renamed key must stop the run. It must never
  write nulls over filled fields.
- Check the library against the installed version and name the file. Read on 2026-11-25:
  `MetadataAwareTextSplitter._get_metadata_str` counts every metadata key that is not excluded
  (llama-index-core 0.14.22, `llama_index/core/node_parser/interface.py:270-281`).
  `upsert_nodes` adds properties with `SET e += ...` and removes none
  (llama-index-graph-stores-neo4j 0.7.0, `neo4j_property_graph.py:367-387`), so a property that
  only `propagate` wrote survives a rebuild of the document and is lost at a reset. That is why
  both the join and the patch carry the group.
- `HierarchicalNodeParser` returned one document's nodes level by level: the root, then 4 middle
  chunks, then 18 leaves, and `start_char_idx` counted from the parent chunk, not from the
  document. `position` and `section` need the offset in the document. Derive it and test it.
- Stage 2 writes chunk properties in two places: the chunk writer of the build
  (`_chunk_nodes_and_rels`), for every document built from then on, and one patch script for
  the rest. The patch chunks a document again, compares the ids with the graph, and writes only
  where they are equal.
- **Three writes reach the live graph, and each is a checkpoint that needs the owner's yes:**
  the Stage 1 patch (58,570 documents), the link pass of Stage 2 (99,520 edges) and the chunk
  patch of Stage 2 (7,435,393 chunks). Each note gives the counts before, the duration of a dry
  run and the counts expected after. Tests run on `tests/graph_double.py` or on the throwaway
  Neo4j of unit 27, never on port 7687.
- No model call and no GPU job in either stage. A test fixture holds a handful of feed records,
  not a feed.
