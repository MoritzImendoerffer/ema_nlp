import os
from pathlib import Path

from dotenv import load_dotenv

# Machine-specific secrets live at ~/.myenvs/ema_nlp.env (never in the repo).
# Variables defined there override environment variables already set in the shell.
_env_file = Path("~/.myenvs/ema_nlp.env").expanduser()
if _env_file.exists():
    load_dotenv(_env_file, override=False)

# github repo responsible for the scraping part
# https://github.com/MoritzImendoerffer/ema_scraper

# Nexcloud dateset storage
nx_datafolder = Path("~/Nextcloud/Datasets/")

# EMA NLP processed data — override with EMA_DATA_DIR env var
EMA_DATA_DIR = Path(os.getenv("EMA_DATA_DIR", "~/Nextcloud/Datasets/ema_nlp")).expanduser()
CORPUS_PATH = Path(os.getenv("EMA_CORPUS_PATH", str(EMA_DATA_DIR / "corpus" / "corpus.jsonl"))).expanduser()
INDEX_DIR = Path(os.getenv("EMA_INDEX_PATH", str(EMA_DATA_DIR / "index"))).expanduser()

# IDMP Onologies
rdf_path = nx_datafolder.joinpath("Pistoia-Alliance-Ontologies/IDMP-O/1.3.0").expanduser()
rdf_file_name = "IdentificationOfMedicinalProductsOntology.rdf"
rdf_file_path = rdf_path.joinpath(rdf_file_name)

# MongoDB config — URI can be overridden in ~/.myenvs/ema_nlp.env
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = "ema_scraper"
MONGO_COL = "web_items"

# Retrieval store: Neo4j PropertyGraphIndex. Connection (NEO4J_URI / NEO4J_USER /
# NEO4J_PASSWORD) is read from the env by harness.indexing.property_graph; the
# active index profile is selected by EMA_INDEX_PROFILE (default neo4j_hier ->
# harness/configs/index/). Postgres/pgvector and the EMA_RETRIEVER faiss/pgvector
# switch were removed in the LlamaIndex/Neo4j refactor — see docs/RETRIEVAL.md.
