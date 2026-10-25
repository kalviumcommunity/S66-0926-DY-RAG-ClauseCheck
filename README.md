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


## Configuration

All settings are environment variables, read through `clausecheck.core.config.Settings`. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY` and `GROQ_API_KEY`. Never commit `.env`.

- Keys are `SecretStr`, so printing the settings shows `**********`.
- If a required key is missing, startup fails and names the variable but prints no values.
- Logs go through a redaction filter that replaces every key with `[REDACTED]`.
- Adding a setting means adding it to `Settings` and to `.env.example`; `tests/unit/test_env_example.py` fails if they differ.
- Gemini is the main LLM. After `LLM_MAX_RETRIES` failures it falls back to Groq.

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
