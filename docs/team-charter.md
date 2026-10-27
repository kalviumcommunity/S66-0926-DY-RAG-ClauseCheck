# ClauseCheck: Team charter

See also: [development-plan.md](planning/development-plan.md) (section 3 for workstreams, section 4 for working rules)

Fill in the blank cells. Update this file by PR when roles change.

## Members

| Name | Role | GitHub handle | Contact |
|---|---|---|---|
| | | | |
| | | | |

## Workstream owners and reviewers

Each workstream has one owner and one reviewer from another workstream, so every PR is reviewed by someone who didn't write it.

| Workstream | Owner | Reviewer |
|---|---|---|
| A: Data & ingestion | | |
| B: Retrieval | | |
| C: Generation & evaluation | | |
| D: App & platform | | |

## Working rules

Taken from [development-plan.md](planning/development-plan.md) section 4.

**Daily**
- 15-minute stand-up at the start of the day: yesterday, today, blockers. Kanban board updated.
- Work on a branch named `w{week}-{workstream}-{short-name}`, e.g. `w3-b-rrf-fusion`.
- At least one PR per person per day. Eval numbers go in the PR description, with the index version, prompt version and parameters used.

**Weekly**
- D1: week kick-off. Confirm the previous exit gate and assign this week's issues.
- D3: mid-week check. Are we on track for the exit gate? Move work or trigger the cut list if not.
- D5: full eval run (from week 3 onward), weekly review with the mentor, exit-gate decision recorded in the PR description.

**Definition of done (every task)**
1. Its PR is reviewed and merged into `main`.
2. Its unit tests pass in CI (lint, unit, integration with the LLM mocked).
3. The related eval number, if any, is written in the PR description.
4. Any config it adds is in `.env.example`, and any decision it makes is reflected in the design documents.

**Rules that apply all sprint**
- No secrets in the repo. `detect-secrets` runs as a pre-commit hook and in CI.
- Every retrieval or prompt change is re-run against the eval set before merge (from week 3).
- Parameters live in `.env`, never hard-coded.
- Prompts are versioned text files (`# v1`, `# v2`, ...). The version is logged with every query.
