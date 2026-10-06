# DeepSeek Agent Runtime Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect DeepSeek to the real ClinLoop Agent path so an API event can be consumed by a Worker, analyzed with a structured model proposal, validated by deterministic rules, persisted, and shown in the clinician console.

**Architecture:** Add a worker-local OpenAI-compatible provider selected explicitly by `AGENT_PROVIDER=deepseek`. The provider receives only a minimal event/workflow context and returns a validated candidate proposal. The WorkflowAgent records model metadata in the existing AgentRun trace, while Guard and repository boundaries remain the only write path for workflow state. Add Redis event publishing and a durable Worker CLI so API events can trigger this path.

**Tech Stack:** Python 3.13-compatible code, Pydantic v2, httpx, FastAPI, SQLAlchemy, Redis Streams, React/TypeScript, pytest, Vitest, Ruff, ESLint.

## Global Constraints

- Synthetic or de-identified data only; never commit `.env`, keys, raw model prompts, raw model responses, or database volumes.
- DeepSeek is opt-in; `AGENT_PROVIDER=mock` remains the CI/offline default.
- The model may propose intent, plan, evidence references, and workflow gaps, but may not directly write Loop state, Review status, Handoff status, or medical-record content.
- Provider failure uses a fail-closed `MODEL_ERROR` stop reason; no finding or state mutation is committed for that event.
- All provider output is strict Pydantic JSON; evidence references must already be visible in the model context and belong to the current patient.
- API and Worker logs persist only safe provider/model/error metadata; never prompts, response bodies, headers, or API keys.
- Existing deterministic demo, evaluation, and full test suite must remain green.

---

### Task 1: Add model-assisted contracts and runtime configuration

**Files:**
- Modify: `packages/contracts/enums.py`
- Modify: `packages/contracts/models.py`
- Modify: `apps/api/app/settings.py`
- Modify: `.env.example`
- Create: `apps/worker/worker/model_contracts.py`
- Test: `tests/contracts/test_agent_model_proposal.py`

**Interfaces:**
- Produce `StopReason.MODEL_ERROR`.
- Produce `AgentContext` and `AgentProposal` Pydantic models in `apps/worker/worker/model_contracts.py`.
- Add settings for `event_bus`, `deepseek_api_key`, `deepseek_base_url`, and `deepseek_model` without changing mock defaults.

- [ ] Write tests that accept a valid proposal, reject unknown intent/event/priority values and out-of-range confidence, and serialize only safe fields.
- [ ] Run `uv run --python 3.13 pytest -q tests/contracts/test_agent_model_proposal.py`; verify it fails because the new enum/models do not exist.
- [ ] Add `MODEL_ERROR`, strict `AgentContext`, and strict `AgentProposal` models. Use `Field(ge=0, le=1)` for confidence and `extra="forbid"` through the existing strict model base.
- [ ] Add the four settings with defaults `EVENT_BUS=noop`, empty DeepSeek key, `https://api.deepseek.com/v1`, and `deepseek-chat`; do not infer provider from a nonempty key.
- [ ] Run the focused contract tests and `uv run --python 3.13 --group dev ruff check packages apps/api/app/settings.py`; expect PASS.
- [ ] Commit `feat: add model proposal contracts and deepseek settings`.

### Task 2: Implement the DeepSeek provider with safe failure codes

**Files:**
- Create: `apps/worker/worker/providers.py`
- Modify: `pyproject.toml` only if the existing `httpx` dependency is insufficient
- Test: `tests/worker/test_deepseek_provider.py`

**Interfaces:**
- Produce `ModelProvider` protocol with `analyze(context: AgentContext) -> AgentProposal`.
- Produce `DeepSeekProvider(endpoint, model, api_key, timeout, transport=None)`.
- Produce `build_model_provider(settings)`, returning the deterministic provider for `mock` and DeepSeek provider for `deepseek`.

- [ ] Write fake-transport tests for HTTPS endpoint validation, Authorization header, model name, JSON request body, valid structured response, timeout, non-2xx response, invalid JSON, and provider response size limits.
- [ ] Run `uv run --python 3.13 pytest -q tests/worker/test_deepseek_provider.py`; verify it fails before implementation.
- [ ] Implement one POST to `{base_url}/chat/completions` with a system instruction, minimal context JSON, `response_format` JSON object, `stream=false`, explicit timeout, no redirects, and `trust_env=False`.
- [ ] Parse the response into `AgentProposal`; convert all remote failures into stable codes such as `MODEL_TIMEOUT`, `MODEL_HTTP_ERROR`, `MODEL_INVALID_RESPONSE`, and `MODEL_REFUSAL` without retaining remote text.
- [ ] Implement `MockProvider.analyze()` as a deterministic proposal used only by offline tests and the existing demo.
- [ ] Run provider tests, Ruff, and a secret scan over tracked files; expect PASS.
- [ ] Commit `feat: add safe DeepSeek model provider`.

### Task 3: Make WorkflowAgent use the provider and expose real trace metadata

**Files:**
- Modify: `apps/worker/worker/agent.py`
- Modify: `apps/worker/worker/planner.py`
- Modify: `apps/worker/worker/run_models.py` only if a safe in-memory trace field is required
- Modify: `packages/contracts/models.py` only if an additive trace field is required
- Modify: `apps/api/app/repositories.py`
- Modify: `apps/api/app/routes/trace.py`
- Test: `tests/worker/test_agent_model_runtime.py`
- Test: `tests/api/test_trace_model_metadata.py`

**Interfaces:**
- `WorkflowAgent(..., provider: ModelProvider | None = None)` uses `build_model_provider()` when no provider is supplied.
- Provider metadata is persisted as safe `AgentRun` trace data in the existing JSON payload boundary: provider name, model name, proposal reference, latency, and error code. `_row_kwargs()` and `_to_contract()` must round-trip this additive metadata without a database migration.

- [ ] Write tests proving a fake provider proposal changes the candidate plan/intent path, appears in the trace, and never directly changes a Loop state.
- [ ] Write a failure test proving provider error produces `MODEL_ERROR`, preserves the triggering event, creates no new finding, and does not call the Guard with a state mutation.
- [ ] Run the focused worker/API tests and verify they fail before implementation.
- [ ] Add provider injection to the Agent. For each model-assisted event, build `AgentContext` from the current event, loop/intent snapshot, recent relevant events, and visible evidence only.
- [ ] Validate proposal patient ID, evidence references, enum values, and confidence before using it; retain deterministic planner fallback only for explicit mock mode.
- [ ] Add safe provider metadata to the trace response. Never return prompt text, raw response text, or secrets.
- [ ] Add the UI label mapping for `MODEL_ERROR` and run focused tests plus the full backend suite.
- [ ] Commit `feat: connect DeepSeek proposals to workflow agent`.

### Task 4: Wire API events to Redis and add a durable Worker command

**Files:**
- Modify: `apps/api/app/dependencies.py`
- Modify: `apps/worker/worker/bus.py`
- Modify: `apps/api/app/main.py`
- Create: `apps/worker/worker/service.py`
- Create: `scripts/run_worker.py`
- Modify: `docker-compose.yml`
- Test: `tests/integration/test_api_worker_deepseek.py`

**Interfaces:**
- `get_event_publisher()` returns Redis publishing when `EVENT_BUS=redis`; `noop` remains API-only mode.
- `process_event(session, agent, event) -> AgentRun` persists the run, findings, and audit data transactionally.
- `scripts/run_worker.py --once` consumes one Redis batch; without `--once` it continues polling. Redis consumption must return an explicit message acknowledgement handle; the Worker acknowledges only after the database transaction completes.

- [ ] Write an integration test with fake Redis and fake provider: POST event, consume it, process it, verify AgentRun and finding persistence, and verify duplicate event id remains rejected.
- [ ] Add a failure test proving persistence completes before the Redis message is acknowledged; a `MODEL_ERROR` run is safely persisted and then acknowledged so one poison message cannot block the stream forever, while persistence failures leave the message pending.
- [ ] Run the integration tests and verify they fail before implementation.
- [ ] Implement Redis publisher creation from settings with explicit `EVENT_BUS=redis`; keep the current no-op publisher for API-only local use. Change `RedisStreamEventBus.consume()` so it does not acknowledge messages automatically and add `ack(message)` for the Worker.
- [ ] Extract demo persistence logic into `apps/worker/worker/service.py`; persist the run, candidate findings, and append an audit entry only after successful validation.
- [ ] Implement the Worker CLI with `--once`, `--count`, and a bounded poll loop. Acknowledge a message only after the database transaction completes.
- [ ] Update Compose to pass `EVENT_BUS=redis`, DeepSeek settings, and run the Worker command without embedding secrets.
- [ ] Run the integration tests and the existing 297-test backend suite.
- [ ] Commit `feat: connect api events to durable workflow worker`.

### Task 5: Show model participation and errors in the clinician console

**Files:**
- Modify: `apps/web/src/api/types.ts`
- Modify: `apps/web/src/components/AgentTracePanel.tsx`
- Modify: `apps/web/src/components/shared.tsx`
- Modify: `apps/web/src/components/WorkflowGapsPanel.tsx` only if model error notices need a shared state
- Test: `apps/web/src/components/AgentTracePanel.test.tsx`

**Interfaces:**
- Trace response includes safe `provider`, `model`, `latency_ms`, `proposal_ref`, and `error_code` fields when available.
- The UI renders `MODEL_ERROR` as a stopped run with a retry/readiness message and never renders prompt or response bodies.

- [ ] Write frontend tests for provider/model metadata, proposal reference, model error rendering, and the existing ACT parameter disclosure.
- [ ] Run `npm --prefix apps/web test -- --run`; verify the new assertions fail before implementation.
- [ ] Add typed fields and a compact “模型参与” metadata row to each run.
- [ ] Add the Chinese label `模型调用失败` for `MODEL_ERROR` and a safe error code display.
- [ ] Run frontend tests, lint, and build.
- [ ] Commit `feat: show model-assisted agent trace`.

### Task 6: Document and manually verify the DeepSeek path

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/demo/runbook.md`
- Create: `docs/development/deepseek-agent-trial.md`
- Test: `tests/release/test_deepseek_configuration.py`

- [ ] Write configuration tests proving keys are not tracked, `AGENT_PROVIDER=mock` does not make network calls, and `AGENT_PROVIDER=deepseek` requires all DeepSeek settings.
- [ ] Add PowerShell commands for a local trial: copy `.env.example`, fill the key locally, start PostgreSQL/Redis, start API, start Worker, POST one synthetic event, open Swagger and the console.
- [ ] Document that only synthetic `P-1001` data may be used and that provider failures stop the run.
- [ ] Document the exact expected trace: provider/model metadata, structured proposal reference, Guard result, and stop reason.
- [ ] Run configuration tests, secret scan, and `scripts/verify_release.py --security-only`.
- [ ] Commit `docs: document DeepSeek Agent trial`.

### Task 7: Full verification, PR, and main integration

**Files:**
- No new source files; update the plan checkboxes and changelog if needed.

- [ ] Run `uv run --python 3.13 scripts/verify_release.py` with the Worker remaining in mock mode for deterministic CI.
- [ ] Run the provider fake-transport suite and the API-to-Worker integration suite.
- [ ] Run frontend tests, lint, and build.
- [ ] Run the synthetic demo and confirm the existing offline path is unchanged.
- [ ] Inspect `git diff --check`, `git status`, and tracked-file secret scan.
- [ ] Push `codex/deepseek-agent-integration`, open a PR against `main`, wait for all GitHub checks, and squash merge only after they pass.
- [ ] Reset the local checkout to `origin/main`, verify the final commit and clean status, and report that the user must fill `.env` locally to make the real DeepSeek call.
