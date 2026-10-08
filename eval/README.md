# Synthetic workflow evaluation

## Database-backed online evaluation

The older four-gap comparison below is a structured-contract benchmark. Its
`ClinLoop` row is context-free and does not measure the database-backed Worker.
For the currently implemented result-follow-up workflow, run:

```powershell
.venv/Scripts/python.exe -m eval.run_online_eval --output artifacts/eval/online-report.json
```

This command replays six labeled synthetic cases through fresh SQLite databases,
the production `process_event` function, read-only tool registry, persisted
findings, and persisted evidence. It compares `rules` (the Worker's existing
non-model intent extractor) with an explicitly labeled deterministic `mock`.
Labels are kept outside event payloads and model context. The report counts
TP/FP/FN/TN, precision, recall, tool calls, model errors, and whether finding
evidence resolves to the expected patient and lab source. A provider error on a
positive case remains a false negative. The committed offline result is an
**engineering regression measurement**, not a DeepSeek or clinical efficacy
result. Six synthetic cases cannot establish generalization or time saved.
The release script asserts a narrow regression floor on the fixed rules
cohort: at least two sourced true alerts, no false alerts, at most one miss,
and no model errors. This prevents an all-miss report from passing the release
gate. It is not a clinical safety threshold.

For the fixed 50-case contest engineering set, run `python -m eval.run_online_eval --provider rules --corpus contest-v1 --output artifacts/eval/contest-rules-local.json`. It has 25 positives and 25 negatives. The current rule baseline is TP 19 / FN 6 / FP 0 / TN 25, or 76% recall and 100% precision on this synthetic set. A deterministic MOCK gives 25/25 recall but 12/25 negative false alerts. Neither result is a live AgentArts measurement. See the [AgentArts evaluation protocol](../docs/agentarts/evaluation-protocol.md) for the frozen cohort and limitations.

After publishing a workflow in AgentArts, set `AGENTARTS_ENDPOINT`, `AGENTARTS_RUNTIME_NAME`, and `AGENTARTS_API_KEY` in the Worker environment, then run `python -m eval.run_online_eval --provider agentarts --corpus contest-v1 --assert-contest-target --output artifacts/eval/agentarts-online-local.json`. The exit code is nonzero below the preregistered 95% recall, 90% precision, 10% negative false-alert rate, 100% evidence-validity, zero model-error gates. The failed report is retained for analysis. This reports engineering performance only; a separate timed human study is needed for efficiency claims.

To run actual DeepSeek inference, explicitly opt in after setting the key in
the current process environment (never commit it):

```powershell
$env:DEEPSEEK_API_KEY = Read-Host "DeepSeek API Key" -AsSecureString | ConvertFrom-SecureString -AsPlainText
.venv/Scripts/python.exe -m eval.run_online_eval --provider deepseek --output artifacts/eval/deepseek-online-local.json
```

Real mode compares the same `rules` cases with `deepseek`. The output is kept
local by `.gitignore`; its default path is
`artifacts/eval/deepseek-online-local.json`. The report stores synthetic case IDs, cohort labels,
scores, provider kind, and model ID, but no event text, prompts, raw responses,
or credential. The model is called on every visible event, so six cases consume
11 API requests. If the model fails, that case is counted rather than dropped.
The online suite covers only `RESULT_WITHOUT_ACKNOWLEDGEMENT`; it does not
validate the other three gap families or a handoff draft.

Task11 implements the shared contracts without modifying the existing worker.
Run from the repository root with Python 3.12:

```powershell
.venv/Scripts/python.exe -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/report.json --comparison-output artifacts/eval/comparison.csv
.venv/Scripts/python.exe -m pytest tests/eval -q
.venv/Scripts/python.exe -m ruff check eval tests/eval
```

`--count100` and `--seed20260928` also work. Counts are nonnegative integers;
zero produces a valid empty report with zero denominators. Largest-remainder
allocation supports arbitrary counts and gives exactly 25 normal, 20
Plan→Order, 20 Order→Execution, 20 Result→Response and 15 Evidence→Handoff
cases at count 100. IDs are neutral and all records synthetic. Generation uses
a local seeded RNG; defect injection returns a detached copy and never mutates
the source. Only supported defects on normal cases are accepted.

The replay clock is `max(event_time, source_time)`: an old event recorded late
is dispatched when available, rather than inserted into earlier worker memory.
Contexts contain only processed, available records. Observable evidence is
derived from those records; case annotations and gold evidence never reach any
predictor. Raw `replay()` results retain actual runs, tool calls and final memory
states. Reports canonicalize runtime UUIDs (including dictionary keys) and
runtime timestamps/durations while retaining clinical times and ID relationships.
Only UUIDs identified in runtime ID fields are renamed; clinical event/source
IDs and evidence citations remain significant even when they are UUID-shaped.
Clinical provenance takes precedence if an ID appears in both roles.
The output is written atomically; provider prompts, credentials, headers,
endpoint URLs and raw HTTP bodies are excluded.

## Methods and honest limitations

`direct_llm` and `rag_template` invoke an injectable model provider. The default
is an explicitly labeled **deterministic abstaining MOCK**: no inference or
engineered detection heuristic is represented as an LLM. RAG retrieves visible
high-priority item records and supplies a static handoff template to that same
provider. `model_calls` counts provider invocations, including MOCK calls.

`rule_engine` implements finite rules over visible synthetic stages at handoff
after the recorded deadline. It can identify missing intermediate records even
when a subsequent record exists. It builds a sourced handoff from observed
planned items. Its performance on this intentionally structured corpus is not
evidence of generalization or clinical effectiveness.

`ClinLoop` calls the actual `apps.worker.worker.agent.WorkflowAgent` on each
available event. The adapter only maps worker outputs to the common prediction
DTOs. This adapter deliberately disables runtime context materialization and has
no database or MCP registry. After the conservative result matcher was added,
it abstains instead of claiming every laboratory result is an actionable gap.
Thus a zero-recall `ClinLoop` row in this report measures this context-free
adapter, **not** the complete online Worker. It has empty actual tool calls and
empty final loop states, does not run DeepSeek, and does not generate a handoff.
No timer, external event bus, durable database, automatic resume routing or
clinical review is exercised. The database-backed integration tests cover a
single matched result/response chain, but do not establish clinical performance.

## Opt-in real HTTP inference

The concrete HTTP provider uses `httpx` with an explicit timeout, no redirects
or automatic retries, and an OpenAI-compatible chat completions endpoint that
supports strict `response_format=json_schema`. Both outgoing schema and local
validation require the complete `CasePrediction` structure: types, enums,
timezone-aware timestamps, required fields, extra-field rejection, patient
identity and no future predictions. Refusal, truncation, malformed content,
transport failures and HTTP errors fail the evaluation rather than silently
producing empty predictions. Tests use `httpx.MockTransport`, with no external
inference. Protocol reference: [official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

Configure these environment variables in your local session without committing
them or putting them in command-line arguments:

- `CLINLOOP_EVAL_ENDPOINT`: full HTTPS `/v1/chat/completions` URL (HTTP allowed
  only for loopback servers); credential-bearing URLs and query strings rejected.
- `CLINLOOP_EVAL_MODEL`: explicit public model identifier, no model default.
- `CLINLOOP_EVAL_API_KEY`: API credential, required.
- `CLINLOOP_EVAL_TIMEOUT_SECONDS`: optional positive finite timeout, default 30.

Then explicitly opt in:

```powershell
.venv/Scripts/python.exe -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/real-report.json --provider eval.baselines.providers:real_http_provider
```

Environment variables alone never enable HTTP. Custom providers can also be
injected in Python or loaded as `--provider module:factory`, declaring `kind`
as `mock` or `real` and implementing `generate(request)`. Real inference has not
been executed or validated against an external service. Provider/model/settings
affect repeatability; canonicalization does not make stochastic outputs identical.

## Metric definitions

All rates are micro-aggregated, use distinct patient/item/type finding identities
and distinct patient/item handoff identities, and return **0.0 plus raw counts**
when their denominator is zero. Metrics assess retained final-case predictions,
not alert latency or clinical timeliness.

| Metric | Numerator | Denominator |
| --- | --- | --- |
| Gap recall | Correct patient/item/type gaps predicted after their prerequisite stages became available | Annotated eligible gaps |
| False alarm rate | Distinct predicted normal patient/item/type opportunities | All normal opportunities, including unaffected edges of defect cases |
| Evidence coverage | Backed findings + backed predicted handoff items | Predicted findings + predicted handoff items |
| Finding evidence coverage | Backed findings | Predicted findings |
| Handoff evidence coverage | Backed predicted handoff items | Predicted handoff items |
| Handoff omission rate | Eligible items absent from a valid-time handoff | All eligible handoff items |

The standard corpus has 75 gaps, 325 normal opportunities and 100 eligible
handoff items. Missing case predictions omit all eligible items. Extra handoff
items do not compensate for omissions. Unknown patient/item/type predictions
and invalid timestamps receive separate counts rather than disappearing.
Gap timing uses the specific prerequisite: PLAN for Plan→Order, ORDER for
Order→Execution, RESULT for Result→Response, and PLAN plus HANDOFF for
Evidence→Handoff. Each prerequisite must satisfy both event and source time;
an alert at plan time cannot earn recall for a later result-response gap.

Evidence references must resolve to real source events with matching patient,
encounter, source ID/type, item/stage provenance, claim and observed time, and
be trusted and available at detection or handoff generation. Patient-submitted
records cannot support confirmed facts, even if their node is relabeled trusted.
Finding citations must all support the relevant stage. Handoff citations are
attributed separately to each item using source provenance: a global nonempty
list cannot back another item. Unknown handoff refs fail conservatively; the
current handoff cannot serve as its own source. Only predicted items enter
coverage; omitted items remain visible in the separate omission metric.

The committed report is regenerated by `scripts/verify_release.py`.
