# Guided Agent Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically confirm and refresh the four-step synthetic Agent trial after each persisted Worker run.

**Architecture:** A small polling utility queries the existing patient-runs endpoint by submitted event ID. The synthetic panel owns the wait and status; the Workspace owns refreshes of patient resources and trace.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing API client.

## Global Constraints

- Fixed synthetic patient `P-1001` and existing API contracts only.
- Bounded, abortable polling; no new server endpoint.
- Do not display raw API keys, prompts, or unverified clinical claims.

---

### Task 1: Polling contract

**Files:** Create `apps/web/src/api/waitForRun.ts`; test `apps/web/src/api/waitForRun.test.ts`.

- [ ] Write tests for matching run, unrelated runs, timeout, and abort.
- [ ] Run tests red; implement bounded polling; run green and commit.

### Task 2: Guided panel and refresh

**Files:** Modify `apps/web/src/components/SyntheticEventPanel.tsx`, `apps/web/src/App.tsx`, `apps/web/src/App.test.tsx`, `docs/development/deepseek-agent-trial.md`.

- [ ] Write component tests for automatic refresh, model error, and timeout wording.
- [ ] Run tests red; connect the panel to polling and refresh callback.
- [ ] Run frontend tests, lint, format, build; update docs and commit.

### Task 3: Release and Git

- [ ] Run `python scripts/verify_release.py` and inspect all output.
- [ ] Push a PR, wait for CI, review, and merge to `main`.
