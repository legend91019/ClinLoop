# MVP safety boundaries

- All committed fixtures are synthetic. Real patient records, credentials and database volumes are rejected by CI.
- MCP calls pass through a registered tool name and the Worker execution policy. Unknown tools are rejected before invocation.
- `ExecutionPolicy.max_steps` defaults to 8 and `timeout_seconds` defaults to 30. A budget stop preserves completed steps and does not write a candidate state change.
- A timeout is recorded as `TOOL_TIMEOUT`; it is not reported as missing clinical evidence.
- The Agent creates candidate findings and state proposals only. The deterministic Guard and clinician review service own high-risk transitions.
- Patient-reported evidence cannot be promoted to system-verified evidence.
- Every finding carries supporting evidence and searched sources. “Not found in searched records” is never changed to “does not exist.”
- Handoff sealing refreshes linked loops and evidence and refuses to seal while a high-risk finding is pending review.
- Audit records are append-only. Run, review, transition and seal actions retain actor, reason and source run references.
- Logging helpers redact API keys, authorization values, passwords, tokens and secrets recursively.
