# ema_nlp
Tinkering with Graph RAG and data from the website of ema.europa.eu, based on ema_scraper

## Strategy

Use scraped data stored in MongoDB together with downloaded pdfs to construct a knowlegde graph using Neo4J

1) Create simple Graph from parsed documents.

2) Analyse logs from ema_scraper for warnings, indicating that the parser strategy with sidebar navigation did not work. 

3) Derive strategy to extract text from nodes (e.g. raw html) and extract metadata as well as text for nodes from step 2.

4) Review text extraction strategy for all other nodes

5) Define schema for nodes

6) Fill nodes with text and metadata.

7) Tinker and have fun