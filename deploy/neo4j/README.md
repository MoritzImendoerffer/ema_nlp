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

## Notes

- Image pinned to `neo4j:5.26`; APOC enabled via `NEO4J_PLUGINS=["apoc"]`
  (LlamaIndex's Neo4j store uses APOC for some property-graph operations).
- Data persists in the `ema_neo4j_data` Docker volume. `docker compose down -v`
  wipes it (full re-index needed afterward).
- The healthcheck runs `cypher-shell 'RETURN 1'`; it needs neither APOC nor data.
