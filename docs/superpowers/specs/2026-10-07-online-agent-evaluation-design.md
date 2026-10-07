# Online Agent evaluation design

## Goal and scope

Measure what the database-backed Worker actually does on synthetic event streams. Keep the existing four-gap structured benchmark as a separate engineering regression suite. The new evaluation measures the currently implemented result-follow-up workflow only; it makes no claim about other gap types or clinical effectiveness.

## Design

Each case has a hidden expected outcome and an ordered visible event stream. A fresh SQLite database is created per case and per method. Events enter the same `ClinicalEventRepository` and `process_event` path as the local trial. The evaluator reads persisted runs, findings, and evidence after processing, then verifies that an alert references the expected patient and a source-backed laboratory result. The provider sees only the current event and Worker-visible history. Case labels never enter event payloads or model context.

The first corpus contains direct blood-culture requests, paraphrases, unrelated notes, and unrelated lab panels. It is deliberately small and fully synthetic, so it can validate the measurement path but cannot establish generalization. A `rules` method uses a no-proposal provider so the Worker's existing intent extractor acts as the ablation. A `mock` method exercises the model boundary and must be labeled MOCK. An opt-in `deepseek` method uses environment-only credentials and is labeled REAL. No default command performs paid inference.

Reports include per-case outcome, TP/FP/FN/TN, precision, recall, evidence validity, provider failures, and provenance. Failed model runs count as misses when an alert is expected; they are never silently excluded. Reports contain no prompts, response bodies, API keys, or raw clinical text. Only synthetic case IDs and short public cohort labels are retained.

## Error handling and limits

Provider exceptions fail with safe error codes, and a failed evaluation does not overwrite the prior report. The benchmark intentionally avoids patient-submitted data and clinical recommendations. The evidence check confirms source and patient linkage, not medical correctness. A contest efficacy claim requires an independently reviewed, broader held-out corpus and clinician time study.

## Acceptance

- The online evaluator runs actual database-backed `process_event` calls and persists findings.
- Rule and mock runs are reproducible, identified by provider kind, and have no credential dependency.
- Real DeepSeek is opt-in, and missing credentials fail before any case runs.
- Positive and negative cases affect metrics; an unrelated result does not count as a correct alert.
- Evidence validity is checked from persisted evidence, with cross-patient references rejected.
- Tests cover the data boundary, provider labeling, scoring, and CLI output.
