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

# IDMP Onologies
rdf_path = nx_datafolder.joinpath("Pistoia-Alliance-Ontologies/IDMP-O/1.3.0").expanduser()
rdf_file_name = "IdentificationOfMedicinalProductsOntology.rdf"
rdf_file_path = rdf_path.joinpath(rdf_file_name)

# MongoDB config — URI can be overridden in ~/.myenvs/ema_nlp.env
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = "ema_scraper"
MONGO_COL = "web_items"