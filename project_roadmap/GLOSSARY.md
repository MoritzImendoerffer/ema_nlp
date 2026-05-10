# Glossary — EMA-RAG-Benchmark

*Plain-language definitions for the regulatory, NLP, and ML terms used across the roadmap, README, and blog post. Organized by topic, not alphabetically — related concepts stay next to each other.*

---

## Regulatory bodies and jurisdictions

**EMA — European Medicines Agency.**
The EU agency that evaluates and supervises medicines for human and veterinary use across the European Union. Based in Amsterdam. Publishes guidelines, scientific opinions, and product authorizations. The source of all the Q&A content in this project.

**FDA — U.S. Food and Drug Administration.**
The U.S. counterpart to EMA. Mentioned in the research report because most existing pharma-regulatory RAG work (QA-RAG) is FDA-scoped — hence the gap this project fills.

**CHMP — Committee for Medicinal Products for Human Use.**
The EMA committee that issues scientific opinions on human medicines. When an EMA Q&A references "CHMP Opinion," it's the formal scientific position that the Q&A interprets for applicants.

**CMDh — Co-ordination group for Mutual recognition and Decentralised procedures – human.**
A coordinating body of national regulators across EU/EEA member states for nationally authorized medicines (as distinct from centrally EMA-authorized ones). You'll see it co-author some Q&A documents alongside EMA.

**ICH — International Council for Harmonisation.**
A joint initiative between regulators (EU, US, Japan, and others) and industry that produces harmonized technical guidelines. EMA documents constantly reference ICH numbers (Q3A, M7, Q9, S9, etc.). Each letter maps to a topic: Q = quality, S = safety, E = efficacy, M = multidisciplinary.

---

## Medicinal product concepts

**API — Active Pharmaceutical Ingredient.**
The chemical or biological substance in a medicine that produces the intended therapeutic effect. Paracetamol is the API of Panadol.

**FP — Finished Product.**
The final medicine as the patient receives it — tablet, capsule, injection, etc. Distinguishes the end product from the ingredients used to make it.

**Excipient.**
An ingredient in a medicine that isn't the API — fillers, binders, stabilizers, preservatives, coatings. Polysorbate 80 from the earlier conversation is an excipient used as a surfactant.

**Substance.**
A generic term for any chemical or biological entity identified by its molecular structure, independent of what role it plays. Polysorbate 80 is a *substance* that *acts as* an excipient in one product and could theoretically act as a process aid in another.

**Dose form / Dosage form / Pharmaceutical form.**
The physical form of the finished product — tablet, capsule, cream, solution, etc.

**Route of administration.**
How the medicine enters the body — oral, intravenous, topical, inhaled, etc.

---

## Regulatory documents and procedures

**MA — Marketing Authorisation.**
The legal permission to market a specific medicine in the EU. Without an MA, a medicine can't be sold.

**MAH — Marketing Authorisation Holder.**
The company that holds the MA and is legally responsible for the medicine on the market. The nitrosamine Q&A is addressed to MAHs.

**MAA — Marketing Authorisation Application.**
The formal submission to EMA seeking an MA. Contains the full dossier of quality, safety, and efficacy data.

**EPAR — European Public Assessment Report.**
A public summary document published after EMA approves (or refuses) a medicine. Describes the scientific assessment. Each approved medicine has one. Out of scope for v1 of this project but relevant for v2.

**SmPC — Summary of Product Characteristics.**
The legally-binding document that describes how a medicine should be used — indications, dosing, contraindications, side effects. Product-specific.

**Variation.**
A change to an existing MA — altering the manufacturing process, the specifications, the packaging, the indications, etc. The project's "Classification of Changes Q&A" is about the rules for categorizing and submitting variations.

**CTD / Module 3.**
Common Technical Document — the standardized dossier structure for an MAA, organized into five modules. Module 3 is the quality module (chemistry, manufacturing, controls). When an EMA Q&A mentions "module 3.2.S" it's referring to the section on the active substance.

---

## Quality / manufacturing terminology

**GMP — Good Manufacturing Practice.**
The regulatory framework for how medicines must be manufactured. GMP inspections check compliance.

**CAPA — Corrective And Preventive Action.**
The formal process a manufacturer runs when something goes wrong — root-cause analysis, corrective action for the existing problem, preventive action to stop recurrence. The nitrosamine Q&A 22 discusses interim limits during CAPA implementation.

**QbD — Quality by Design.**
An approach to pharmaceutical development that builds quality into the process through systematic design, understanding of critical parameters, and control strategy — rather than testing quality in at the end. One of your three test URLs was the QbD Q&A page.

**CQA — Critical Quality Attribute.**
A physical, chemical, biological, or microbiological property of a product that must be within a limit to ensure product quality. Think: "how pure does the API need to be, and what's the measurement target."

**AI — Acceptable Intake** (in the regulatory/toxicology sense — not "artificial intelligence").
The maximum daily amount of a substance (typically an impurity) considered to pose negligible risk over a lifetime. For nitrosamines, the AI is typically expressed in nanograms per day. **Watch out for this double-meaning collision with machine-learning "AI" — the nitrosamine Q&A uses "AI" constantly in the toxicology sense.**

**TTC — Threshold of Toxicological Concern.**
A generic exposure level (typically 1.5 µg/day) below which an impurity is considered to pose minimal risk. Nitrosamines are "cohort of concern" — more stringent than TTC applies.

**LoQ — Limit of Quantification.**
The lowest concentration at which an analytical method can reliably measure a substance with acceptable accuracy and precision.

**ppm / ppb — parts per million / parts per billion.**
Concentration units. 1 ppm = 1 mg impurity per kg product.

**Q3A, Q3B, M7, Q9, S9, etc.**
ICH guideline identifiers. Roughly: Q3A/B cover impurities in drug substances and products, M7 covers genotoxic (DNA-damaging) impurities, Q9 covers quality risk management, S9 covers drug products for advanced cancer.

---

## Master data and identifiers (EU pharmaceutical data world)

**IDMP — Identification of Medicinal Products.**
An ISO set of standards (ISO 11238, 11239, 11240, 11615, 11616) that define how to uniquely describe a medicinal product worldwide. Matters because it's the conceptual backbone of how EU regulators structure product information — but the Pistoia ontology version covers the *classes* (MedicinalProduct, Substance, …), not the *instances* (specific drugs). Deferred to v2+ in this project.

**SPOR — Substances, Products, Organisations, Referentials.**
EMA's master-data system, with four registries:
- **SMS** — Substance Management System (ingredients like Polysorbate 80)
- **PMS** — Product Management System (specific medicinal products)
- **OMS** — Organisation Management System (companies like Pfizer, regulatory agencies)
- **RMS** — Referentials Management System (controlled vocabularies like dose forms, units of measurement, routes of administration)

Accessible via public APIs. Useful if the benchmark ever needs entity linking (e.g., mapping "Tween 80" to Polysorbate 80). Deferred.

**xEVMPD / Article 57.**
A database of all medicines authorized in the EEA, submitted by MAHs under Article 57 of EU regulation. Less useful for Q&A work; more useful for EPAR-scale analytics.

**CEP — Certificate of Suitability** (to a European Pharmacopoeia monograph).
A certificate issued by EDQM confirming that a substance meets the relevant Pharmacopoeia quality standard. Cited in nitrosamine Q&A 16.

**ASMF — Active Substance Master File.**
A dossier submitted by an API manufacturer describing the confidential parts of their manufacturing process. MAHs reference it without the confidential parts being exposed.

**EDQM — European Directorate for the Quality of Medicines & HealthCare.**
The Council of Europe body that maintains the European Pharmacopoeia and issues CEPs.

---

## NLP and RAG terminology

**RAG — Retrieval-Augmented Generation.**
An architecture where an LLM is given relevant documents (retrieved from some corpus) as context before it answers. The "retrieval" step is separate from the "generation" step. Most real-world LLM applications on private data use RAG.

**Vanilla RAG / Flat RAG.**
A single-pass RAG system: one retrieval, one generation, no loops. The baseline this project builds.

**Agentic RAG.**
A RAG system where an agent (an LLM orchestrating tool calls in a loop) decides when to retrieve, reformulates queries, plans multi-step reasoning, and critiques its own answers. The control loop replaces the straight pipeline. CLADD and PaperQA2 are examples.

**Graph RAG / Knowledge-Graph RAG.**
A RAG variant where the corpus is (or is augmented by) a structured knowledge graph — nodes for entities, edges for relationships. Enables queries like "all products containing Polysorbate from EU manufacturers" that flat retrieval can't express cleanly. Deferred to v2 in this project.

**Embedding.**
A numerical vector representation of text. Similar texts have similar vectors. The math behind "semantic search."

**Embedding model.**
The neural network that produces embeddings. BGE-large-en is one example. Different models produce different embedding spaces — not interchangeable.

**Vector database / vector store.**
A database optimized for finding nearest-neighbor vectors (most similar embeddings). Qdrant, Chroma, FAISS, Pinecone are examples.

**Chunking.**
Splitting long documents into smaller pieces before embedding. Chunk size and boundaries affect retrieval quality. In this project chunks are pre-defined — each Q&A is one chunk.

**Top-k retrieval.**
Retrieving the k most similar chunks to a query. "Top-5" means 5 chunks.

**Reranking.**
A second-stage scoring of retrieved chunks, usually with a more expensive model, to re-order the top-k before giving them to the generator.

**BM25.**
A classic keyword-based retrieval algorithm (not neural). Often complementary to embedding-based retrieval; the two combined is called "hybrid search."

**Query reformulation.**
Rewriting a user's query before retrieval — expanding acronyms, adding synonyms, breaking a complex query into sub-queries.

**NER — Named Entity Recognition.**
Finding mentions of entities (drugs, companies, procedures) in text and tagging them. Needed for entity linking. Deferred.

**Entity linking.**
Mapping a mention ("Tween 80") to its canonical identifier (Polysorbate 80, SMS ID 100000099999).

**Ontology.**
A formal specification of concepts in a domain and their relationships. IDMP-O is an ontology. An ontology defines *classes* (the schema); *instances* live elsewhere.

**T-box / A-box.**
Ontology jargon. T-box = "terminology box" = the schema/classes. A-box = "assertions box" = the specific instances. The Polysorbate point from earlier was that IDMP is a T-box without the A-box you'd need for real entity linking.

---

## Evaluation terminology

**Benchmark.**
A fixed set of test inputs plus expected outputs plus scoring metrics, used to compare systems. MIRAGE, MedQA, PubMedQA are biomedical benchmarks. This project is building an EMA regulatory benchmark.

**Gold answer / Ground truth.**
The reference answer considered correct. In this project, the gold answer is the EMA-authored answer text.

**Recall@k.**
Fraction of relevant documents (gold sources) that appear in the top-k retrieval results. Tests whether the retriever found what it should have.

**Precision@k.**
Fraction of top-k retrieval results that are actually relevant. Tests whether the retriever returned mostly noise or mostly signal.

**Faithfulness.**
Does the generated answer only claim things supported by the retrieved context? Measures hallucination. Scored by an LLM judge in most modern RAG evaluations.

**Correctness.**
Does the generated answer match the gold answer semantically? Also typically scored by LLM judge.

**LLM-as-judge.**
Using an LLM to score the output of another LLM against gold. Not perfect; noisy; best validated against a hand-graded sample.

**Ablation.**
An experiment where you change one component of a system (turn a feature on/off, swap a model) while holding everything else constant, to isolate that component's effect.

**Pre-registration.**
Stating your hypothesis and expected results *before* running the experiment. Guards against motivated reasoning when reading your own numbers.

**Few-shot / Zero-shot.**
Zero-shot = asking the model with no examples. Few-shot = giving the model a few input-output examples in the prompt before asking. "SME-written few-shot" = examples hand-crafted by a domain expert.

**CoT — Chain-of-Thought.**
Prompting a model to show its reasoning step-by-step before giving a final answer. "Self-generated CoT" = the model produces its own reasoning (as opposed to following an SME-written reasoning template).

**Process reward.**
A reward signal on intermediate steps of a multi-step task, as opposed to only rewarding the final answer. Used in RAG-Gym to train agent planning.

---

## Project-specific terminology

**Q&A (in this project).**
An expert-authored question-answer pair published by EMA. The unit of both the corpus and the benchmark.

**Cross-reference.**
An explicit "see Q&A N" pointer inside an EMA Q&A document. In the corpus schema these become `cross_refs` — the edges that make multi-hop retrieval evaluable.

**Question types (T1–T4).**
The four-way stratification of benchmark questions:
- T1 Lookup — single source, direct answer
- T2 Scoping — requires disambiguating among topically adjacent Q&As
- T3 Multi-hop — requires traversing cross-references
- T4 Synthesis — requires combining ≥2 Q&As from different documents

**Topic path.**
The URL-derived breadcrumb describing where a Q&A lives in the EMA site hierarchy. Used for stratification and for topic-aware retrieval ablations.

**Corpus vs benchmark.**
*Corpus* = the raw normalized Q&A pairs, usable as a retrieval source. *Benchmark* = the stratified evaluation questions with gold answers. Two separable deliverables.

---

## Name collisions to watch

**"AI"** — means *Acceptable Intake* in the nitrosamine Q&A and related toxicology docs. Means *Artificial Intelligence* everywhere else. Context disambiguates, but search-and-replace breaks things.

**"MA"** — Marketing Authorisation (regulatory). Also sometimes a column abbreviation in reports. Never expand blindly.

**"Q&A" vs "QA"** — "Q&A" = the EMA document format (questions and answers). "QA" = quality assurance. Keep the ampersand when you mean the document.
