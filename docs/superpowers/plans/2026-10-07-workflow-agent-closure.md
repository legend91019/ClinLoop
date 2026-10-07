# Workflow Agent Evidence Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ClinLoop real read-only tool calls, evidence-gated gap detection, recoverable event delivery, and a usable synthetic trial.

**Architecture:** The provider proposes read-only tools, while the Worker supplies a patient-scoped registry. A deterministic verifier consumes tool results and event metadata. A persistent publish queue bridges the API/Redis transaction gap. The UI exposes patient runs, including unbound failures.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Redis Streams, Pydantic, React/TypeScript, pytest, Vitest.

## Global Constraints

- Synthetic data only; no real patient data or keys in Git.
- No model-initiated write tool.
- Never claim an absent record proves absence; Finding must cite evidence and searched sources.
- Existing demo and public contracts remain compatible.

### Task 1: Evidence-gated Agent execution

**Files:** `apps/worker/worker/model_contracts.py`, `apps/worker/worker/agent.py`, `apps/worker/worker/service.py`, `apps/worker/worker/verification.py`, `tests/worker/test_agent_evidence.py`.

- [ ] Add a test with two patients and two independent result loops: only the uniquely matched result may create a Finding.
- [ ] Add a test where an explicit acknowledgement exists at the event's visibility time: no Finding.
- [ ] Add a test asserting model-selected, allowlisted read tools appear in `AgentRun.tool_calls` with result refs and bounded output.
- [ ] Implement correlation and verification as a pure function; invoke read tools in the Worker with a strict allowlist and fail closed on tool errors.
- [ ] Run focused worker/API tests; commit.

### Task 2: Event delivery and recovery

**Files:** `apps/api/app/routes/events.py`, `apps/api/app/db_models.py`, `apps/worker/worker/bus.py`, `scripts/run_worker.py`, migration, `tests/integration/test_delivery_recovery.py`.

- [ ] Write failing tests for database commit followed by Redis outage and for reclaiming a pending message after Worker restart.
- [ ] Implement a durable pending-publication table and replay command, Redis pending claim, and post-commit ack.
- [ ] Run integration tests and migration checks; commit.

### Task 3: Patient run visibility and synthetic event entry

**Files:** `apps/api/app/routes/trace.py`, `apps/web/src/api/client.ts`, `apps/web/src/App.tsx`, `apps/web/src/components/AgentTracePanel.tsx`, tests.

- [ ] Write failing API/UI tests for a run with no Loop and a synthetic NOTE event submission.
- [ ] Add patient-scoped trace endpoint and a clearly labeled synthetic input control with loading/error states.
- [ ] Run frontend tests, lint, build; commit.

### Task 4: Evidence, docs and Git integration

- [ ] Run full backend tests, release script, Compose validation and secret scan.
- [ ] Update docs with exact model/tool/verification behavior and current limitations.
- [ ] Push a PR; merge after CI; sync the primary `main` checkout.
