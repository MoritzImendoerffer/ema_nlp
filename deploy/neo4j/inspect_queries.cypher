// Paste-ready inspection queries for the Neo4j Browser (http://localhost:7474).
// Login: neo4j / $NEO4J_PASSWORD (set in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env).
// Run one statement at a time (the Browser executes the whole editor content).
// CLI equivalents: scripts/inspect_graph.py {overview,links,doc,cypher}.
//
// Graph model (docs/RETRIEVAL.md):
//   (:Document)-[:HAS_CHUNK]->(:Chunk),  (:Chunk)-[:PARENT_OF]->(:Chunk),
//   (:Document)-[:LINKS_TO {kind, link_context, document_type, anchor}]->(:Document)

// ── 1. Census ────────────────────────────────────────────────────────────────

// Node + relationship counts (instant, from the counts store via APOC)
CALL apoc.meta.stats() YIELD labels, relTypesCount RETURN labels, relTypesCount;

// Documents by category (the steering dimension)
MATCH (d:Document)
RETURN coalesce(d.category, '(unset)') AS category, count(*) AS docs
ORDER BY docs DESC;

// Enrichment coverage — category (all), doc_type (PDFs, from EMA JSON export),
// audience + site_topic (HTML, from page badges). See docs/RETRIEVAL.md §7.
MATCH (d:Document)
RETURN d.source_type AS source_type, count(*) AS docs,
       count(d.category) AS category, count(d.doc_type) AS doc_type,
       count(d.audience) AS audience, count(d.site_topic) AS site_topic
ORDER BY docs DESC;

// EMA authoritative document type (PDFs) — finer than category
MATCH (d:Document) WHERE d.doc_type IS NOT NULL
RETURN d.doc_type AS doc_type, count(*) AS docs ORDER BY docs DESC LIMIT 30;

// Curated subject taxonomy from page badges (HTML) — not derivable from URL
MATCH (d:Document) WHERE d.site_topic IS NOT NULL
RETURN d.site_topic AS site_topic, count(*) AS docs ORDER BY docs DESC;

// ── 2. LINKS_TO boilerplate audit ───────────────────────────────────────────
// Boilerplate signature: a few targets absorbing most edges, nav-ish anchors
// ("Home", "Contact", ...). Pre-scoping, 74 chrome targets held 94.4% of edges.

// Edge histogram by DOM context (file_component / card_or_listing / inline / other)
MATCH ()-[r:LINKS_TO]->()
RETURN r.link_context AS context, r.kind AS kind, count(*) AS edges
ORDER BY edges DESC;

// Top in-degree targets — chrome pages would dominate this list
MATCH ()-[:LINKS_TO]->(b:Document)
WITH b, count(*) AS in_edges ORDER BY in_edges DESC LIMIT 25
RETURN in_edges, b.category AS category, coalesce(b.title, b.source_url) AS target;

// Most-repeated anchor texts — nav boilerplate repeats the same anchor everywhere
MATCH ()-[r:LINKS_TO]->()
RETURN r.anchor AS anchor, count(*) AS edges, count(DISTINCT startNode(r)) AS from_docs
ORDER BY edges DESC LIMIT 25;

// Spot-check: random sample of edges as a table
MATCH (a:Document)-[r:LINKS_TO]->(b:Document)
WITH a, r, b ORDER BY rand() LIMIT 25
RETURN coalesce(a.title, a.source_url) AS source, r.anchor AS anchor,
       r.kind AS kind, r.link_context AS context,
       coalesce(b.title, b.source_url) AS target;

// ── 3. Visual graph views (Browser renders these as a graph) ───────────────

// Random slice of the link graph — eyeball hub structure
MATCH p = (:Document)-[:LINKS_TO]->(:Document)
WITH p ORDER BY rand() LIMIT 100
RETURN p;

// Link neighbourhood of one page (edit the CONTAINS filter)
MATCH (d:Document)
WHERE toLower(d.source_url) CONTAINS 'nitrosamine'
WITH d LIMIT 1
MATCH p = (d)-[:LINKS_TO*1..2]-(:Document)
RETURN p LIMIT 200;

// One document with its chunk tree (small-to-big structure)
MATCH (d:Document)
WHERE toLower(coalesce(d.title, '')) CONTAINS 'nitrosamine'
WITH d LIMIT 1
MATCH p = (d)-[:HAS_CHUNK]->(:Chunk)
RETURN p LIMIT 100;

// ── 4. Drill-down ───────────────────────────────────────────────────────────

// Everything linking TO a given document, with anchors (edit the filter)
MATCH (a:Document)-[r:LINKS_TO]->(b:Document)
WHERE toLower(coalesce(b.title, b.source_url)) CONTAINS 'ich q3'
RETURN coalesce(a.title, a.source_url) AS source, r.anchor AS anchor,
       r.link_context AS context
ORDER BY context LIMIT 50;

// Dangling check: documents with no chunks (ingest gaps)
MATCH (d:Document)
WHERE NOT (d)-[:HAS_CHUNK]->(:Chunk)
RETURN count(d) AS docs_without_chunks;

// ── 5. Topic subgraphs: hub candidates + subgraph preview ───────────────────
// (docs/next/topic_subgraphs.md — curation surface for manage_topic_hubs.py)

// Hub candidates: regulatory_overview pages ranked by qualified out-fanout
// (curated link contexts weighted x2; archive/news titles are a red flag —
// the propose CLI penalizes them, here you just eyeball).
MATCH (h:Document {category: 'regulatory_overview'})-[e:LINKS_TO]->(t:Document)
WHERE t.category IN ['qa', 'scientific_guideline', 'regulatory_procedure', 'regulatory_overview']
   OR t.doc_type IS NOT NULL
WITH h,
     sum(CASE WHEN e.link_context IN ['file_component', 'card_or_listing'] THEN 1 ELSE 0 END) AS curated,
     sum(CASE WHEN e.link_context = 'inline' THEN 1 ELSE 0 END) AS inline
WHERE curated + inline >= 5
RETURN h.title AS title, curated, inline, 2 * curated + inline AS score, h.source_url AS url
ORDER BY score DESC LIMIT 30;

// Membership coverage per hub key (after build + propagate)
MATCH (d:Document) WHERE d.topic_hubs IS NOT NULL
UNWIND d.topic_hubs AS hub
RETURN hub, count(*) AS members ORDER BY members DESC;

// One hub's stamped subgraph — composition (edit the key)
MATCH (d:Document) WHERE 'referral_procedures' IN d.topic_hubs
RETURN d.category AS category, d.doc_type AS doc_type, count(*) AS n
ORDER BY n DESC;

// Visual: a hub's members and the link edges between them (edit the key)
MATCH (a:Document) WHERE 'referral_procedures' IN a.topic_hubs
OPTIONAL MATCH p = (a)-[:LINKS_TO]->(b:Document)
WHERE 'referral_procedures' IN b.topic_hubs
RETURN a, p LIMIT 300;

// Preview a candidate hub's qualified 2-hop walk BEFORE confirming it
// (edit the seed filter + qualifier to match the proposed walk)
MATCH (s:Document)
WHERE toLower(s.source_url) CONTAINS 'referral-procedures-human-medicines'
MATCH p = (s)-[:LINKS_TO*1..2]->(t:Document)
WHERE ALL(n IN nodes(p)[1..] WHERE
      (n.category IN ['qa', 'scientific_guideline', 'regulatory_procedure', 'regulatory_overview']
       OR n.doc_type IN [])
      AND NOT coalesce(n.audience, '') IN ['Veterinary', 'Corporate'])
WITH DISTINCT t
RETURN t.category AS category, t.doc_type AS doc_type, count(*) AS n
ORDER BY n DESC;
