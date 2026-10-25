# Evaluation set

`questions.jsonl` is the labelled question set that every retrieval or prompt change is measured against. Each line is one `Question` (`eval/schema.py`).

## How the questions were written

There are three groups.

**Real-contract (`real`, 30 questions).** Chosen from contracts that are in the database, covering renewal terms, termination for convenience, liability caps, warranties, minimum commitments, insurance, audit rights, liquidated damages and contract terms. Each question is worded the way a buyer would ask it and names the supplier. The gold chunk is the clause that answers it, found by matching the CUAD label span against the ingested chunks and checked by reading the clause. Only whole-clause chunks are used where possible, so the gold IDs do not change when the window settings change. Clauses with redaction markers are not used.

Three questions are **amendment questions**. Their gold is the amendment chunk, because the amended term is the answer. The `notes` field names the original clause chunk that a correct answer must not rely on alone.

**Exact-value (`exact`, 22 questions).** One per fact in `data/raw/synthetic/ground_truth.jsonl`: a unit price, payment terms, an effective date, a certificate expiry date, number or issuer. The gold is the chunk that holds the value: the table chunk for prices and payment terms, the page chunk for the effective date and for certificates.

**Unanswerable (`unanswerable`, 15 questions).** The correct response is a refusal, so `should_refuse` is true and the gold is empty. Eight ask for a term that is not in any document for a named supplier (checked by searching that supplier's chunks), four name a supplier that is not in the corpus, and three are outside the domain.

## The split

Each group is split about 60% `tune` and 40% `heldout`, assigned with `random.Random` seeded from 42, so both splits contain every group. The overall tune share is 60%.

## Running it

Always run the runner as a module so the `eval` imports resolve:

```bash
python -m eval.run_eval --split tune --stage retrieval --retriever NAME --k 5
```

- `--retriever NAME` is a name in `eval.run_eval.RETRIEVERS`. The registry is empty until the retrieval PRs fill it. An unknown name prints the available ones and exits with 3.
- `--stage answer` and `--stage e2e` exit with 3 until PR 9 and 10.
- Results are written to `eval/results/{date}_{stage}_{split}.json`.
- To score a retriever in code: `eval.metrics.evaluate_retrieval(questions, retrieve_fn, k=5)`. It skips the unanswerable questions and returns recall@k, MRR and per-question detail.

## The held-out rule

The held-out split is not run before week 5 day 4. `--split heldout` is refused with exit code 2 unless `--allow-heldout` is passed. Do not tune retrieval, prompts or thresholds against it, and do not read its results while tuning.

## Keeping the gold IDs valid

Gold chunk IDs come from the ingested database. If the chunker, the cleaner or the corpus changes, run `python -m clausecheck.ingest --rebuild` and then `pytest tests/unit/test_eval_set.py`. It fails if a gold ID no longer exists. If it does, re-map the question to the new chunk by hand and keep the question text.
