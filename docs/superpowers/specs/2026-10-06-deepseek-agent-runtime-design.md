# DeepSeek Agent Runtime Integration Design

## Goal

Make the ClinLoop Agent visibly model-assisted and runnable end to end from an
API event to a persisted Agent trace, while preserving the existing safety
boundary: the model proposes intent, plan, evidence interpretation, and
workflow gaps; deterministic domain rules and clinician review control all
state changes.

## Scope

This change adds an opt-in DeepSeek provider and a local Worker path that can
consume API events. The default `mock` configuration remains available for
offline tests and deterministic demos. DeepSeek is enabled explicitly with
environment variables and is never enabled merely because a key exists.

The first model-assisted decisions are:

1. `NOTE_CREATED`: classify the finite intent taxonomy, expected evidence,
   waiting event types, priority, and a short rationale.
2. `LAB_RESULT_CREATED`: assess whether the visible workflow context supports a
   response gap and return an evidence reference candidate.
3. `PROGRESS_NOTE_CREATED`: identify a new dependency loop candidate when the
   note describes a follow-up result.

The model does not write Loop state, Review status, Handoff status, database
rows, or medical-record content.

## Runtime architecture

```text
FastAPI event route
  -> configured EventPublisher (Redis in worker mode, no-op only in API-only mode)
  -> RedisStreamEventBus
  -> scripts/run_worker.py
  -> WorkflowAgent + DeepSeekProvider
  -> deterministic Guard and repository persistence
  -> AgentRun / Finding / AuditLog
  -> Doctor console trace, review, and handoff
```

The existing in-memory `run_demo.py` path remains as a deterministic smoke
test. The new Worker command is the path used to experience API-driven Agent
execution.

## Provider contract

Add a worker-local provider protocol with one structured operation:

```python
analyze(context: AgentContext) -> AgentProposal
```

`AgentContext` contains the current event, the current loop and intent
snapshot, recent relevant events, and evidence already visible at that point.
It never contains API credentials, full patient history, hidden evaluation
labels, or unrelated records.

`AgentProposal` contains only validated candidate fields:

- finite `intent_type` or `null`;
- `goal` and `rationale` strings;
- `expected_evidence` and `waiting_for` values from contract enums;
- `priority` from `LOW`, `NORMAL`, `HIGH`, or `CRITICAL`;
- a confidence in `[0, 1]`;
- optional evidence references that must already exist in context.

The DeepSeek implementation uses an OpenAI-compatible HTTPS chat-completions
endpoint and locally validates the JSON response with Pydantic before the
proposal reaches the Agent. The provider records only safe metadata such as
provider name, model, latency, and error code in the trace; prompts, response
text, headers, and keys are never persisted.

## Configuration

`.env` receives local-only settings:

```dotenv
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=replace-locally
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
AGENT_TIMEOUT_SECONDS=30
AGENT_STEP_BUDGET=8
```

The API key is never committed. `AGENT_PROVIDER=mock` remains the default for
CI and offline tests. The provider is selected explicitly; setting a key alone
does not cause network calls.

## Agent behavior and failure handling

The Agent records the model proposal as part of the REASON/PLAN trace, then
applies deterministic validation. A valid proposal can create a candidate
intent or finding, but cannot directly transition a Loop. Evidence scope and
patient ownership are checked before persistence.

The selected failure policy is fail-closed:

- timeout, transport failure, invalid JSON, refusal, schema mismatch, or
  provider HTTP error produces a safe `MODEL_ERROR` stop reason;
- no new finding or state change is committed for that event;
- the AgentRun stores only a stable error code and provider metadata;
- the API/Worker log contains no raw provider response or secret.

## API and Worker integration

When `EVENT_BUS=redis`, the API publisher sends accepted events to the
configured Redis stream. `scripts/run_worker.py` consumes the stream, builds a
minimal context, invokes the configured provider, persists the AgentRun and
candidate findings, and acknowledges the message only after the transaction
is complete. API-only mode keeps the no-op publisher and is explicitly labeled
as persistence-only in the runbook.

## UI changes

The Agent Trace panel will show:

- provider and model metadata;
- model-assisted rationale summary;
- structured proposal references;
- safe error code and `MODEL_ERROR` when the run stops;
- the same existing five phases and tool parameter disclosure behavior.

The UI will not display prompts, full model responses, API keys, or unsupported
clinical recommendations.

## Testing and acceptance

Tests will cover:

- DeepSeek request shape, authorization, timeout, HTTPS validation, and strict
  response parsing using a fake HTTP transport;
- no secret or provider response in AgentRun serialization or logs;
- model proposal cannot bypass Guard or patient/evidence ownership checks;
- provider failure creates `MODEL_ERROR` without a finding or state mutation;
- Redis API-to-Worker flow persists the run before acknowledging the message;
- the console renders provider metadata and model errors;
- an offline mock path keeps the full existing suite green.

Manual acceptance uses a local `.env`, synthetic `P-1001` data, Swagger
`POST /api/v1/events`, the Worker command, and the console's Agent Trace. No
real patient data is permitted.

## Non-goals

- automatic diagnosis, treatment recommendation, or order writing;
- allowing model output to close or resolve a high-risk Loop;
- adding model calls to the fixed deterministic evaluation report by default;
- storing full prompts or model responses;
- production authentication or multi-tenant deployment.
