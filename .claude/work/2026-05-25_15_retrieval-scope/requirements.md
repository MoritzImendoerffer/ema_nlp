# Question

> Which documents are searched if I ask a question? The pipeline should query
> all documents in the mongo database. Is this the case, or are only the
> EMA Q&A documents used for generating the answers?

## Short answer

**Only Q&A pairs are searched.** The pipeline does not query MongoDB at
question time, and the corpus that backs the index covers only documents
from which the extractors could pull explicit Q&A pairs (HTML accordions +
numbered-heading PDFs). The bulk of MongoDB content — regular EMA web
pages and non-Q&A PDFs — never enters the retrievable index.

See `exploration.md` for the data-flow walk-through and the gap analysis.
