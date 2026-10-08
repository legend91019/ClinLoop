# AgentArts contest implementation plan

## 1. Runtime integration

- Add an opt-in `agentarts` provider with validated endpoint, runtime name, key, timeout, and strict published-runtime response parsing.
- Add request/response contract tests and safe error-code tests before implementation.
- Keep all existing Guard, audit, review, and idempotent event persistence behavior.

## 2. Platform and demo package

- Document exact AgentArts node configuration, prompt contracts, knowledge file, authentication, deployment, and rollback.
- Provide a versioned workflow contract and a synthetic-only, authenticated read-only evidence endpoint for AgentArts tool nodes, with patient/time scoping tests.
- Expose AgentArts provenance in the existing trace UI and make the public demo path unambiguous.

## 3. Evaluation

- Freeze a larger labeled synthetic replay set with separate development and held-out partitions and no labels in input payloads.
- Extend the database-backed online runner to invoke the published AgentArts runtime and save an auditable report with per-case outcomes, failure counts, latency, model/runtime ID, corpus version, and Git revision.
- Add target gates for recall >= 95%, precision and evidence correctness; run only after live credentials are available. Never substitute mock results.
- Prepare a counterbalanced human timing study protocol and empty data template; execute with actual participants before claiming time saved.

## 4. Release

- Run backend, frontend, safety, and replay checks; inspect Git diff and secret scan.
- Publish a hosted HTTPS demo and AgentArts workflow in the user's region, capture screenshots and a live evaluation run.
- Merge the verified implementation to `main` and push. Mark contest readiness only when cloud deployment and live evidence pass.
