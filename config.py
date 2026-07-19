import os
from pathlib import Path

from dotenv import load_dotenv

# Machine-specific secrets in ema_nlp.env (never in the repo). Search order:
#   1. $EMA_ENV_FILE                              — explicit override
#   2. ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env   — canonical (moved 2026-07-19,
#      lives with the synced dataset folder)
#   3. ~/.myenvs/ema_nlp.env                      — legacy location, kept as a
#      fallback until every machine has synced the move
# The first existing file wins; already-set shell variables are never overridden.
ENV_FILE_CANDIDATES = tuple(
    Path(p).expanduser()
    for p in (
        os.getenv("EMA_ENV_FILE") or "",
        "~/Nextcloud/Datasets/ema_nlp/ema_nlp.env",
        "~/.myenvs/ema_nlp.env",
    )
    if p
)
ENV_FILE: Path | None = next((p for p in ENV_FILE_CANDIDATES if p.exists()), None)
# Canonical path named in error messages ("set X in ...") across the codebase.
ENV_FILE_HINT = "~/Nextcloud/Datasets/ema_nlp/ema_nlp.env (or $EMA_ENV_FILE)"
if ENV_FILE is not None:
    load_dotenv(ENV_FILE, override=False)

# github repo responsible for the scraping part
# https://github.com/MoritzImendoerffer/ema_scraper

# Nexcloud dateset storage
nx_datafolder = Path("~/Nextcloud/Datasets/")

# EMA NLP processed data — override with EMA_DATA_DIR env var
EMA_DATA_DIR = Path(os.getenv("EMA_DATA_DIR", "~/Nextcloud/Datasets/ema_nlp")).expanduser()
CORPUS_PATH = Path(os.getenv("EMA_CORPUS_PATH", str(EMA_DATA_DIR / "corpus" / "corpus.jsonl"))).expanduser()
INDEX_DIR = Path(os.getenv("EMA_INDEX_PATH", str(EMA_DATA_DIR / "index"))).expanduser()

# Eval/visualization artifacts (KB map, chain HTMLs, eval outputs). Lives in the
# Nextcloud dataset folder so results sync across machines (same folder layout
# everywhere) — override with EMA_RESULTS_DIR.
RESULTS_DIR = Path(os.getenv("EMA_RESULTS_DIR", str(EMA_DATA_DIR / "results"))).expanduser()

# IDMP Onologies
rdf_path = nx_datafolder.joinpath("Pistoia-Alliance-Ontologies/IDMP-O/1.3.0").expanduser()
rdf_file_name = "IdentificationOfMedicinalProductsOntology.rdf"
rdf_file_path = rdf_path.joinpath(rdf_file_name)

# MongoDB config — URI can be overridden in ema_nlp.env (see ENV_FILE above)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = "ema_scraper"
MONGO_COL = "web_items"

# Retrieval store: Neo4j PropertyGraphIndex. Connection (NEO4J_URI / NEO4J_USER /
# NEO4J_PASSWORD) is read from the env by harness.indexing.property_graph; the
# active index profile is selected by EMA_INDEX_PROFILE (default neo4j_hier ->
# harness/configs/index/). Postgres/pgvector and the EMA_RETRIEVER faiss/pgvector
# switch were removed in the LlamaIndex/Neo4j refactor — see docs/RETRIEVAL.md.
