# Online Agent Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an honest, reproducible evaluation of the database-backed result-follow-up Agent chain.

**Architecture:** Generate a small synthetic event corpus with labels held outside the event stream. Replay each case through a fresh SQLite database and the production `process_event` function. Score persisted findings and evidence against labels, and expose rules, mock, and opt-in DeepSeek modes.

**Tech Stack:** Python 3.12, SQLAlchemy, Pydantic, pytest, existing Worker and repositories.

## Global Constraints

- Synthetic data only. No patient information or credentials in reports.
- The existing `eval.run_eval` benchmark remains unchanged and separately labeled.
- No paid inference by default. Real provider requires an explicit CLI mode and environment credential.
- Evaluate the implemented result-follow-up workflow only.

---

### Task 1: Corpus and score contract

**Files:** Create `eval/online/cases.py`, `eval/online/scoring.py`; test `tests/eval/test_online_cases.py`, `tests/eval/test_online_scoring.py`.

**Interfaces:** `online_cases() -> list[OnlineCase]`; `score_case(case, observed) -> CaseScore`; `summarize(scores) -> dict`.

- [ ] Write tests for hidden labels, distinct positive/negative cohorts, and deterministic IDs.
- [ ] Run tests and confirm expected failures.
- [ ] Implement the smallest corpus contract and scoring functions.
- [ ] Run targeted tests and commit.

### Task 2: Database-backed replay

**Files:** Create `eval/online/runtime.py`; test `tests/eval/test_online_runtime.py`.

**Interfaces:** `run_case(case, provider) -> ObservedCase`.

- [ ] Write a test that requires persisted Worker findings and source-backed evidence.
- [ ] Run it red; implement fresh SQLite replay through `process_event`.
- [ ] Test an unrelated result and provider error; run tests and commit.

### Task 3: CLI and documentation

**Files:** Create `eval/run_online_eval.py`; modify `eval/README.md`, `docs/release/mvp-checklist.md`; test `tests/eval/test_online_cli.py`.

**Interfaces:** `python -m eval.run_online_eval --provider rules|mock|deepseek --output PATH`.

- [ ] Write tests for default safe mode, explicit real mode, credential failure, and report labels.
- [ ] Run red; implement CLI and atomic JSON output.
- [ ] Run targeted and full tests, lint, and release verification; update docs with actual results.
- [ ] Commit and push through Git workflow.
