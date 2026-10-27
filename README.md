# ClauseCheck: Procurement contract assistant

ClauseCheck is a RAG-powered assistant that helps procurement teams instantly verify negotiated terms across hundreds of supplier contracts, pricing agreements, and compliance documents. Ask a question in plain English and get a grounded answer backed by clause-level citations, so buyers can trust every response without digging through PDFs.

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . -r requirements.txt
pre-commit install
pytest -q
```

Copy `.env.example` to `.env` and add your API keys once it exists. Never commit `.env`.

## Folder map

| Path | What is in it |
|---|---|
| `clausecheck/` | The Python package: `core`, `ingest`, `rag`, `store`, `llm`, `services`, `api`, `prompts` |
| `frontend/` | Streamlit app |
| `scripts/` | Corpus download, validation and maintenance scripts |
| `notebooks/` | Exploration notebooks (outputs stripped by `nbstripout`) |
| `eval/` | Evaluation questions, runner and results |
| `data/` | Corpus manifest, `raw/` source files and `uploads/` (contents git-ignored) |
| `tests/` | `unit/`, `integration/` and `api/` tests |
| `docs/` | Requirements, planning, architecture, data and UX documents; start with the [team charter](docs/team-charter.md) and the [PRD](docs/requirements/PRD.md) |

Data attribution is in [NOTICE](NOTICE).
