from pathlib import Path

# github repo responsible for the scraping part
# https://github.com/MoritzImendoerffer/ema_scraper

# Nexcloud dateset storage
nx_datafolder = Path("~/Nextcloud/Datasets/")

# IDMP Onologies
rdf_path = nx_datafolder.joinpath("Pistoia-Alliance-Ontologies/IDMP-O/1.3.0").expanduser()
rdf_file_name = "IdentificationOfMedicinalProductsOntology.rdf"
rdf_file_path = rdf_path.joinpath(rdf_file_name)


# MongoDB config
MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "ema_scraper"
MONGO_COL = "web_items"