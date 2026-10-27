# ClauseCheck: PR prompts for Claude Code

There are 12 files here, one per PR, in merge order. Each file is a complete brief for Claude Code. It covers what to build, the exact files it may touch, the interfaces other PRs depend on, and **the tests that prove the PR works**.

## How the tests work

The tests in each file are the **contract** for that PR, and they follow test-driven development:

1. Claude Code first copies the test files into the repo **exactly as written**.
2. It then writes the code until every test passes.
3. **It may not edit, weaken, skip or delete a test to make it pass.** If a test looks wrong, it stops and explains why, and you decide.

Later PRs depend on the function names, signatures and field names fixed in earlier PRs. Keeping the tests unchanged is what holds the 12 PRs together.

## Workflow for each PR

```bash
git checkout main && git pull
git checkout -b <branch name from the PR file>
mkdir -p docs/pr-prompts && cp ~/Downloads/pr-prompts/PR-XX-*.md docs/pr-prompts/
claude
```

Then give Claude Code this prompt:

```text
Read docs/pr-prompts/PR-XX-<name>.md and implement it completely.
1. First create every test file listed under "Tests" exactly as written.
2. Then implement the code until `pytest -q` passes with no failures and no skips other than the ones the brief allows.
3. Only touch the files listed in "Scope". Do not edit any test from this or earlier PRs.
4. Run `ruff check .`, `black --check .` and `pytest -q`, and show me the output.
5. Finish with a list of the files you changed and anything you could not do.
```

## Before you merge (checklist for each PR)

- [ ] `pytest -q` passes locally. Run the whole suite, not only the new tests, so you know earlier PRs still work.
- [ ] `ruff check .` and `black --check .` are clean.
- [ ] `pre-commit run --all-files` passes (from PR 1 onward).
- [ ] Every step under **Manual checks** in the PR file passes.
- [ ] `git diff --stat main` shows only files listed in the PR's **Scope**.
- [ ] `git diff main -- tests/` shows only **added** test files from this PR, with no edits to earlier ones.
- [ ] Every new setting appears in both `clausecheck/core/config.py` and `.env.example`.
- [ ] Eval numbers and command outputs the PR's manual checks ask for are pasted into the PR description.
- [ ] CI is green on the PR.

## Owners

- **Diya — Data, Retrieval & Platform Foundations:** PRs 1–8 (branches `a-*`).
- **Teammate — Generation, Application & Delivery:** PRs 9–12 (branches `b-*`). Start PRs 9–10 in week 2 on branches stacked on PR 7/8, coding against the fakes in the tests; rebase onto `main` once PR 8 merges.
- Each person reviews the other's PRs.

## Order

| # | File | Branch |
|---|---|---|
| 1 | PR-01-repo-scaffold.md | `a-repo-scaffold` |
| 2 | PR-02-config-llm-client.md | `a-config-llm-client` |
| 3 | PR-03-corpus-sourcing.md | `a-corpus-sourcing` |
| 4 | PR-04-loaders-cleaner.md | `a-loaders-cleaner` |
| 5 | PR-05-chunker-ingest-cli.md | `a-chunker-ingest-cli` |
| 6 | PR-06-eval-set.md | `a-eval-set` |
| 7 | PR-07-embed-vector-search.md | `a-embed-vector-search` |
| 8 | PR-08-hybrid-rerank.md | `a-hybrid-rerank` |
| 9 | PR-09-grounded-generation.md | `b-grounded-generation` |
| 10 | PR-10-query-service-followups.md | `b-query-service-followups` |
| 11 | PR-11-api-upload.md | `b-api-upload` |
| 12 | PR-12-frontend-deploy.md | `b-frontend-deploy` |

PR 6 can be built in parallel with PRs 4 and 5, but it must merge before PR 7.

## Rules that apply to every PR

- **No real API calls in tests.** Gemini, Groq, EDGAR and Hugging Face are always faked or mocked. Only the eval runs and the manual checks use real services.
- **Settings live in `.env`**, never hard-coded. Every new setting goes in `Settings` and `.env.example`, and `tests/unit/test_env_example.py` enforces this.
- **No secrets anywhere.** Tests use the sentinel key `TEST-SENTINEL-7f3a`.
- **Design docs win over guesses.** When a brief says "see docs/…", Claude Code reads that doc. If the doc and the brief disagree, the brief's interfaces win (tests depend on them), and the doc gets a note.
- Python ≥ 3.11, type hints everywhere, and a docstring on every public function.
