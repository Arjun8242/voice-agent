# RAG Retrieval Engineering Plan
## Evaluation, Search Strategy, Latency Optimization, and Measurable Results

**Status:** Working plan — proposed methods are hypotheses until tested  
**Purpose:** Keep our retrieval work, experiments, measurements, and engineering decisions aligned. Update this document as we inspect the codebase and produce evidence.

---

## 1. Project objective

Improve the retrieval component of the existing voice agent so it finds the right knowledge-base evidence reliably and quickly. Demonstrate the improvement with reproducible measurements and documented trade-offs.

This is a **retrieval-focused plan**. It covers how we will inspect, evaluate, improve, and validate the RAG retrieval pipeline. Agent orchestration and LangGraph are deliberately outside this document and will be handled separately.

### What success looks like

- We know how the current retriever works and have a reproducible baseline.
- We have a human-verified benchmark of representative queries and relevant supporting chunks.
- We can identify whether failures come from ingestion, chunking, retrieval, ranking, context construction, or answer generation.
- We have compared relevant search strategies instead of choosing them by trend or intuition.
- We can explain why the final strategy was selected and which alternatives were rejected.
- We report real before/after quality and latency measurements, with conditions and limitations.
- Retrieval improvements do not break the existing voice pipeline.

### Principles

1. Measure the current system before changing it.
2. Change one major variable at a time.
3. Keep a holdout set where dataset size permits.
4. Preserve stable source and chunk IDs for evaluation.
5. Treat target metrics as project-specific acceptance criteria, not universal standards.
6. Never invent performance claims; only report measured results.
7. Do not add a database, retrieval method, reranker, or infrastructure component unless evidence supports it.

---

## 2. Scope

### In scope

- Audit current document ingestion, chunking, embeddings, indexing, retrieval, and context assembly.
- Create a verified evaluation dataset.
- Establish baseline retrieval quality, answer grounding, and latency.
- Compare dense retrieval, sparse retrieval (BM25), hybrid retrieval (dense + sparse fusion), top-K settings, and optional reranking.
- Inspect retrieval failures and classify their root causes.
- Measure p50/p95 at retrieval-stage and end-to-end levels.
- Optimize latency while preserving retrieval quality.
- Produce a system-design diagram, experiment report, decision log, and evidence-backed resume claims.

### Out of scope for this document

- LangGraph, agent routing, and tool orchestration.
- Rewriting the voice interface or STT/TTS pipeline.
- Changing the vector database before auditing the existing setup.
- Adding Redis, Qdrant, or other infrastructure only for résumé keywords.
- Multi-agent systems or unrelated advanced RAG patterns.

---

## 3. Current state and details to verify

Known from project discussion:
- The backend has been converted to Python.
- The project has folders resembling `server/`, `pipeline/`, `providers/`, `services/`, `tests/`, and `data/`.
- A knowledge-base ingestion/retrieval path already exists.
- The voice agent has an existing STT/LLM/RAG/TTS flow.

We must inspect the code to confirm:
- Vector store or index, storage mode, and index parameters.
- Embedding model and document/query embedding behavior.
- Chunking method, chunk size, overlap, metadata, and stable identifiers.
- Current search algorithm, top-K, filters, similarity metric, score thresholds, and sorting.
- Whether retrieval is dense-only, sparse-only, or already hybrid.
- How duplicates are handled and how final context is selected or truncated.
- Current latency instrumentation and tests.
- Whether the converted backend's end-to-end voice flow still works.

These are unknown until code inspection; do not assume a particular library or database.

---

## 4. Proposed retrieval system design

### 4.1 Indexing / ingestion path

```text
Source documents
      |
      v
Parse and clean content
      |
      v
Chunk documents
      |
      +--> Assign stable chunk IDs, source IDs, and useful metadata
      |
      +-------------------------------+
      |                               |
      v                               v
Generate chunk embeddings        Build lexical index (BM25)
      |                         [only if tested/adopted]
      v                               |
Existing vector index                 v
      |                          Sparse index
      +---------------+---------------+
                      |
             Offline benchmark
```

Dense and sparse indexes should share stable source/chunk IDs so search results can be merged and evaluated against verified relevance labels. A BM25 index is optional, not an automatic requirement.

### 4.2 Query-time retrieval path

```text
Query from existing voice pipeline
              |
              v
         Query preparation
              |
              +---------------------------+
              |                           |
              v                           v
        Dense vector search          BM25 search
         [current path]              [optional]
              |                           |
              +-------------+-------------+
                            |
                  Rank fusion (e.g. RRF)
                  [only for hybrid search]
                            |
                    Candidate chunks
                            |
                    Optional reranker
                            |
                   Context selection
               (deduplicate, fit token budget,
                preserve required evidence)
                            |
                  Context ready for LLM
                            |
                  Existing answer pipeline
```

Use only the branches justified by experiments. For dense-only retrieval, skip BM25 and fusion. For hybrid retrieval, independent dense and sparse queries can often run in parallel. Reranking is optional and should be retained only if its measured quality benefit justifies its latency and cost.

### 4.3 Evaluation and observability plane

```text
Versioned queries + verified supporting chunk IDs
                       |
                       v
             Repeatable retrieval runs
                       |
          +------------+-------------+
          |            |             |
          v            v             v
      Recall/rank   Context/answer   Latency/cost
       metrics        metrics        metrics
          |            |             |
          +------------+-------------+
                       |
              Failure analysis
                       |
              Decision log + report
                       |
              Regression benchmark
```

RAGAS may help evaluate context and answer quality. Direct retrieval metrics such as Recall@K and MRR/nDCG are also needed. A metric library does not replace verified ground truth or human review.

---

## 5. Step-by-step work plan

### Phase 0 — Audit the existing retriever

**Small tasks**
1. Trace how source files become chunks and how chunks enter the index.
2. Locate the exact retrieval function called at query time.
3. Record the embedding model, vector store, chunking configuration, top-K, filters, distance metric, and any score thresholds.
4. Inspect how retrieved chunks are ordered, deduplicated, and assembled into context.
5. Run a representative smoke test and make sure the converted backend still works.
6. Add minimal timing instrumentation around the existing stages, if absent.

**Deliverables**
- Current retrieval flow diagram.
- List of files/functions that implement ingestion and retrieval.
- Current configuration snapshot.
- Smoke test and initial failure notes.

**Exit condition:** We can reproduce a retrieval query and explain exactly how its result was produced.

### Phase 1 — Build a human-verified evaluation dataset

Start with approximately 50 representative queries. Expand this number based on corpus size, query diversity, and the stability of results.

Include:
- Direct factual questions.
- Paraphrased questions and natural spoken language.
- Exact names, IDs, technical terms, and rare keywords.
- Questions needing evidence from more than one chunk.
- Questions where two similar policies or concepts could be confused.
- Ambiguous/incomplete queries where appropriate.
- Unanswerable questions whose answers are absent from the knowledge base.
- Realistic speech-to-text transcription mistakes if they occur in the current voice workflow.

For each answerable query, store:
- Query text.
- Expected answer or required answer facts.
- Verified relevant chunk IDs and source IDs.
- Query category and difficulty, if useful.
- Whether multiple evidence chunks are required.

Have a human verify reference answers and supporting chunks. LLM-generated queries can help draft a dataset but are not ground truth until reviewed.

If feasible, divide the dataset into:
- A tuning set used to make retrieval choices.
- A holdout set used only for final comparison.

**Deliverables**
- Versioned benchmark file.
- Relevance-labeling rules.
- Verified reference answers and chunk IDs.

**Exit condition:** The current retriever can be scored repeatedly against known relevant evidence.

### Phase 2 — Establish baseline metrics

Run the existing configuration against the same benchmark and record:
- Retrieved chunk IDs, rank, raw score, and source metadata.
- Number of candidates and final context chunks.
- Query embedding duration.
- Dense-search duration.
- Sparse-search duration, if applicable.
- Fusion and reranking durations, if applicable.
- Context-construction duration.
- Total query-to-context-ready duration.
- Context token count.
- End-to-end answer quality on the same queries for a selected test subset.

Calculate suitable metrics:
- Recall@5 and Recall@10, adjusting K to match actual use.
- MRR@K and/or nDCG@K to assess ranking.
- RAGAS Context Recall and Context Precision where references support these metrics.
- Faithfulness and answer correctness on end-to-end tests.
- Correct abstention on unanswerable questions.
- Retrieval p50/p95 and, separately, end-to-end voice response latency.

**Metric distinctions**
- Recall@K asks whether known relevant chunks are present among the top K results.
- RAGAS Context Recall estimates how much of the reference answer's information is supported by retrieved context. It is not the same as Recall@K.
- MRR emphasizes the rank of the first relevant result; nDCG can account for multiple results and graded relevance.
- Context precision/relevance helps diagnose irrelevant context, but the precise definition depends on the selected metric implementation/version.
- Faithfulness checks support in the provided context; it does not prove that the source itself is true.
- LLM-judge scores can be noisy. Check a sample manually and record evaluator/model versions.
- Similarity scores alone do not prove a result is relevant.

**Deliverable:** Baseline results table plus per-query logs and failure examples.

### Phase 3 — Diagnose retrieval failures

For every failure, identify its earliest plausible cause:

1. **Ingestion failure:** document missing, parsing corrupted, or key content omitted.
2. **Chunking failure:** evidence split apart, context lost, or chunks too broad.
3. **Candidate recall failure:** relevant chunk is absent from the initial results.
4. **Ranking failure:** relevant chunk is present but ranks too low.
5. **Filtering/metadata failure:** correct evidence is excluded by a filter or metadata mismatch.
6. **Context assembly failure:** relevant evidence is removed, truncated, duplicated, or poorly formatted after search.
7. **Generation failure:** evidence reaches the LLM but the answer is wrong, unsupported, or fails to abstain.
8. **Latency failure:** profiling identifies a specific slow stage.

The fix depends on the diagnosis. Do not use reranking to fix missing documents or a relevant chunk that never entered the candidate pool.

**Deliverable:** Failure taxonomy with representative examples and an intervention hypothesis for each major category.

### Phase 4 — Run controlled retrieval experiments

Use the same corpus, benchmark queries, chunking, and embedding model when comparing retrieval methods. Change one primary variable at a time.

#### Experiment A: Current dense baseline
Record all selected quality metrics, latency, and context size. This is the reference point for every later comparison.

#### Experiment B: Tune top-K
Test a small range of candidate/final K values. Observe how recall, ranking, context tokens, and latency change. Do not reduce K on latency alone.

#### Experiment C: Sparse search with BM25
Build or enable a lexical index if exact terms, names, IDs, or vocabulary mismatches are relevant failure types. Measure BM25 by itself so its contribution is understood.

BM25 is a lexical ranking method. It can excel at exact term matches but may miss semantically similar queries with little wording overlap.

#### Experiment D: Hybrid retrieval with rank fusion
Run dense and BM25 searches and combine their ranked results using Reciprocal Rank Fusion (RRF) or another justified fusion approach. RRF is a useful starting point because dense and sparse raw scores may not be directly comparable.

Measure:
- Recall@K and ranking quality before/after fusion.
- Performance by query category.
- p50/p95 latency.
- Duplicate candidate rate and context tokens.

#### Experiment E: Optional reranking
Apply a relevance model to an initial candidate list and select the final top-K.

Measure:
- Ranking improvement (MRR/nDCG).
- Context Precision and answer quality.
- Added latency and cost.
- Whether the initial candidate pool already contained the required evidence.

A reranker normally reorders the candidates it receives; it cannot recover relevant evidence that was never retrieved into that pool.

#### Experiment F: Context selection
Test safe duplicate removal and context selection. Preserve evidence for multi-part questions; do not prune solely to minimize tokens.

Check whether context size and answer latency improve without unacceptable loss of retrieval recall or answer correctness.

**Deliverable:** Reproducible experiment matrix and evidence-supported recommendation.

### Phase 5 — Improve latency while guarding recall

Measure latency distributions, not only averages. Use a representative workload and enough requests for p95 to be meaningful.

Capture separately:
- Query embedding.
- Dense search.
- BM25 search.
- Fusion.
- Reranking.
- Context assembly.
- Query-to-context-ready.
- LLM time to first token and generation duration.
- Voice end-of-speech to first audio and full response duration, on an end-to-end subset.

Candidate optimizations to test only where relevant:
1. Precompute document embeddings during ingestion; do not re-embed the entire corpus on every query.
2. Reuse database/network connections where supported.
3. Execute independent dense and sparse branches in parallel.
4. Tune approximate-nearest-neighbor index settings against a high-recall reference.
5. Adjust candidate pool and final K using measured quality trade-offs.
6. Remove safe duplicates and avoid sending irrelevant chunks.
7. Cache repeated work only when query semantics, freshness, privacy, and invalidation requirements make it safe.
8. Investigate network, index, and initialization overhead if profiling points there.

For approximate search, benchmark recall against exact or more exhaustive search on a test sample if possible. Faster index settings can reduce recall.

Do not add individual-stage p95 values to estimate end-to-end p95. Measure the full path directly, because stage timings vary together and percentile arithmetic is not generally additive.

Record workload size, concurrency, deployment region, provider/model versions, warm/cold behavior, and test date.

**Deliverable:** Before/after latency report with retrieval-quality guardrails.

### Phase 6 — Select the final retrieval configuration

Set acceptance criteria after establishing the baseline and the product's latency needs. Example criteria to discuss—not hard-coded universal standards:
- Minimum Recall@K on the holdout set.
- Acceptable context precision/answer correctness.
- Required behavior on unanswerable queries.
- Maximum retrieval and end-to-end p95 latency.
- Acceptable token usage and cost.

Decision rules:
- If the relevant chunk is absent, investigate ingestion, chunking, metadata filters, embeddings, candidate depth, and hybrid retrieval.
- If it is present but ranked too low, test fusion and reranking.
- If retrieval is strong but the answer is wrong, investigate context assembly and generation rather than changing search blindly.
- If reranking improves relevance but exceeds the latency budget, try a smaller candidate pool or omit it.
- If BM25 does not improve measured outcomes enough to justify complexity, do not retain it only for sophistication.
- If changes improve the tuning set but degrade holdout results, investigate overfitting.
- Keep only changes whose quality, latency, cost, and maintenance effects are understood.

**Deliverable:** Final decision memo describing the selected design and why the alternatives were accepted, rejected, or deferred.

### Phase 7 — Regression and final report

Re-run the baseline and selected final configuration on the same benchmark. Validate:
- Retrieval-quality change.
- Latency change under comparable conditions.
- Answer correctness and grounding.
- Abstention on unanswerable queries.
- No regressions in the existing voice flow.
- Reproducibility from documented code/configuration.

**Deliverables**
- Final metric table.
- Retrieval architecture diagram.
- Experiment and failure-analysis report.
- Decision log.
- Reproducible benchmark command or script.
- Resume bullets supported by real evidence.

---

## 6. Metrics reference

| Metric | Question answered | Notes |
|---|---|---|
| Recall@K | Does top-K include the verified relevant chunks? | Requires chunk/document relevance labels |
| MRR@K | How high is the first relevant result? | Useful for queries with one primary answer chunk |
| nDCG@K | Are relevant results ordered well, including graded relevance? | Requires relevance labels |
| RAGAS Context Recall | How much reference-answer information is supported by retrieved context? | Needs reference data and evaluator validation |
| RAGAS Context Precision | Is the retrieved context relevant relative to the reference/query? | Confirm behavior in the chosen RAGAS version |
| Faithfulness | Are claims in the generated response supported by the provided context? | Does not verify source truth |
| Answer correctness | Does the answer match trusted facts/reference? | Use human review or validated references |
| Abstention quality | Does the system avoid unsupported claims when evidence is absent? | Test both answerable and unanswerable queries |
| p50 latency | Median duration | Can conceal tail delays |
| p95 latency | Duration within which 95% of observed requests finish | Needs a representative sample |
| Context tokens | How much material is passed to generation? | More context is not always better |
| Cost per query | Resource/API cost of a query | Depends on model/provider usage and pricing |

---

## 7. Result table template

Populate with actual observations only. Record dataset version, corpus/index version, embedding/provider versions, retrieval parameters, test date, concurrency, and measurement method alongside the table.

| Version | Configuration | Recall@5 | Recall@10 | MRR@10 / nDCG@10 | Context Precision | Context Recall | Faithfulness | Retrieval p50 | Retrieval p95 | End-to-end p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | Current retriever | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| B | Dense, tuned K | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| C | BM25 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| D | Hybrid + RRF | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| E | Hybrid + reranker | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Final | Selected configuration | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Not every metric must be calculated for every phase, but the baseline and final system should be compared consistently.

---

## 8. Architecture decision log template

For each material decision, record:

- **Question:** What design choice needs to be made?
- **Observed issue:** Which query failures or metric results show the problem?
- **Options considered:** What alternatives are plausible?
- **Hypothesis:** What measurable effect is expected, and why?
- **Experiment design:** What stays fixed and what changes?
- **Results:** Metrics, variability, cost, and example queries.
- **Trade-offs:** Quality, latency, complexity, maintainability, and operational risks.
- **Decision:** Adopt, reject, or defer.
- **Follow-up:** What needs continued monitoring or a regression test?

Example: “Test hybrid retrieval because exact policy identifiers were missing from dense top-K. Accept the change only if verified identifier-query recall improves without exceeding the agreed p95 target.”

---

## 9. Resume evidence

Only use these as templates until actual experiments are completed.

> Benchmarked dense and hybrid RAG retrieval on **[N] human-verified queries**, improving Recall@10 from **[A] to [B]** while maintaining retrieval p95 at **[C] ms** under **[test conditions]**.

> Evaluated retrieval precision, context recall, answer faithfulness, and latency; used failure analysis to select **[final strategy]** over **[alternative]** based on measured quality–latency trade-offs.

To defend the result in an interview, be ready to explain the baseline, dataset construction, relevance labels, experimental controls, failure cases, latency methodology, and why a rejected approach was not adopted.

---

## 10. Useful references

- RAGAS documentation: https://docs.ragas.io/
- OpenTelemetry documentation: https://opentelemetry.io/docs/
- LangChain retrieval concepts (for background only): https://docs.langchain.com/oss/python/langchain/retrieval

Use the documentation matching the installed library/version when implementation starts; APIs and metric behavior may change over time.

---

## 11. Immediate next steps

1. Inspect the existing ingestion and retrieval code.
2. Confirm the vector store, embedding model, chunking, metadata, top-K, and filtering logic.
3. Verify the converted backend and run a repeatable retrieval smoke test.
4. Create the initial verified benchmark.
5. Run the existing retriever and capture baseline quality and latency.
6. Classify failed queries before choosing interventions.
7. Compare retrieval strategies through controlled experiments.
8. Choose the final configuration based on measured quality, latency, and maintainability.
9. Update this document with real results and decisions.

**Working agreement:** This document is the shared plan for RAG retrieval engineering. Proposed components are experiments, not commitments to add every method. The implementation and verified evidence determine what stays in the final design.
