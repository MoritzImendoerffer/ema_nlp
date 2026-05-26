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

# Postgres + pgvector — used by harness.embed_pg / harness.retrieve_pg.
# Real DSN (with secret) belongs in ~/.myenvs/ema_nlp.env; the default below
# matches the Docker compose stack under deploy/postgres/ for first-run dev.
PG_DSN = os.getenv("PG_DSN", "postgresql://ema_nlp:ema_nlp@localhost:5432/ema_nlp")

# Retriever dispatch: "pgvector" (default — chunks table in Postgres; full EMA
# narrative corpus) or "faiss" (legacy FAISS index over Q&A corpus.jsonl,
# kept for back-compat experiments and benchmark-only runs).
# Flipped to "pgvector" default by NARR-028 (2026-05-26).
EMA_RETRIEVER = os.getenv("EMA_RETRIEVER", "pgvector")