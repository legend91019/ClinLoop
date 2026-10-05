# Changelog

## v0.1.0-mvp — 2026-10-05

### Included

- Event-driven workflow continuity contracts, persistence, API and Redis/in-memory event bus.
- Workflow Agent with suspend/resume, re-plan, evidence-backed findings, deterministic Guard and audit trail.
- React clinician console with timeline, loops, evidence, Agent trace, finding review and handoff sealing.
- Four-method synthetic evaluation over 100 cases with fixed seed `20260928`.
- Reproducible `P-1001` demo and release verification scripts.

### Boundaries

- Synthetic data only; single-patient canonical demo.
- Limited intent taxonomy and no real EHR/FHIR write integration.
- The Agent proposes workflow actions; clinician review controls high-risk transitions.
- Evaluation results are engineering verification, not evidence of clinical effectiveness.
