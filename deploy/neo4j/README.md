# Neo4j — PropertyGraph store (LlamaIndex-first refactor)

Neo4j backs the LlamaIndex `PropertyGraphIndex` introduced in the
`refactor/llamaindex-retrieval-pipeline` work (work unit 20). It replaces the
former Postgres + pgvector retrieval store: it holds the entity (page/PDF) and
chunk nodes plus `has_chunk` / parent–child / `links_to` edges, and its **native
vector index** (Neo4j ≥ 5.15) serves chunk-embedding retrieval — so there is no
separate vector store.

## Start

```bash
scripts/start_services.sh          # brings up Mongo + Neo4j, health-checked
cd deploy/neo4j && docker compose up -d   # Neo4j only
```

- Bolt (driver / LlamaIndex): `bolt://localhost:7687`
- Browser (HTTP): http://localhost:7474

## Credentials / env

Set in `~/.myenvs/ema_nlp.env` (defaults are dev-only):

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=ema_nlp_dev_pw      # >= 8 chars (Neo4j 5.x rejects shorter)
```

The compose file reads `NEO4J_USER` / `NEO4J_PASSWORD` at `up` time to set
`NEO4J_AUTH`. Change the password by setting `NEO4J_PASSWORD` before `up` (and
wiping the `ema_neo4j_data` volume if the DB was already initialised with the
old one — Neo4j fixes the password at first init).

## Inspecting the graph

Two tools, same queries:

- **Neo4j Browser (visual viewer)** — already bundled with the container at
  http://localhost:7474 (login `neo4j` / `$NEO4J_PASSWORD`). Renders query
  results as an interactive graph — use it to eyeball link neighbourhoods and
  chunk trees. Paste-ready queries (census, LINKS_TO boilerplate audit,
  visual graph views, drill-downs) live in
  [`inspect_queries.cypher`](inspect_queries.cypher); run one statement at a
  time.
- **CLI** — `scripts/inspect_graph.py` (read-only, plain `neo4j` driver):

  ```bash
  python scripts/inspect_graph.py overview        # node/edge census + indexes
  python scripts/inspect_graph.py links           # LINKS_TO quality audit
  python scripts/inspect_graph.py doc <id|url-substring>
  python scripts/inspect_graph.py cypher "MATCH (d:Document) RETURN count(d)"
  ```

  `links` prints the boilerplate fingerprint (in-degree concentration,
  link_context histogram, repeated anchors, random samples). Audited
  2026-07-12: top-10 targets absorb 3.3% of the 99,520 edges (pre-scoping
  chrome baseline was 94.4%) — the main-content-scoped extraction is working.

## Notes

- Image pinned to `neo4j:5.26`; APOC enabled via `NEO4J_PLUGINS=["apoc"]`
  (LlamaIndex's Neo4j store uses APOC for some property-graph operations).
- Data persists in the `ema_neo4j_data` Docker volume. `docker compose down -v`
  wipes it (full re-index needed afterward).
- The healthcheck runs `cypher-shell 'RETURN 1'`; it needs neither APOC nor data.
