# v0.1.0-mvp release checklist

## Product and safety

- [x] Six event types are represented: note, order, lab, consult, progress note and handoff (plus patient evidence).
- [x] Five workflow gap families are represented in contracts and synthetic evaluation: intent/plan, plan/order, order/execution, result/response and handoff continuity.
- [x] Suspend/resume and re-plan are covered by Worker lineage tests and the demo readiness check.
- [x] Findings retain original evidence IDs and searchable source scopes.
- [x] Clinician review is required before high-risk resolution or handoff sealing.
- [x] Direct LLM, RAG + template, rule engine and ClinLoop evaluation methods are reported.

## Evidence

- [x] Fixed seed `20260928`, 100 synthetic trajectories.
- [x] `artifacts/eval/report.json` and `artifacts/eval/comparison.csv` generated.
- [x] `artifacts/eval/online-report.json` measures six database-backed synthetic result-follow-up cases with separate rules and MOCK labels.
- [x] `scripts/check_demo_ready.py` passes the canonical `P-1001` event chain.
- [x] Backend, frontend, integration, evaluation and security checks pass.

## Known limitations

- Synthetic data only and one canonical patient demonstration.
- Intent taxonomy is intentionally finite.
- No real EHR/FHIR writes or production multi-patient scheduling.
- Online Worker evidence-backed gap detection currently covers a uniquely matched lab result/response path. The other gap families need online detection and validation before production use.
- The context-free ClinLoop evaluation adapter abstains and does not measure the database-backed Agent chain or real DeepSeek quality.
- The online result-follow-up evaluation is a small engineering corpus. Its MOCK row is not real model inference, and no clinician-reviewed effectiveness or time-savings claim is supported yet.

## AgentArts contest gate (pending)

- [x] Published-runtime adapter, strict proposal validation, authenticated read-only evidence tools, and fixed 50-case engineering corpus implemented locally.
- [x] Rule baseline measured: TP 19 / FN 6 / FP 0 / TN 25, 76% recall on 50 synthetic cases.
- [x] AgentArts workflow and SOP knowledge base created in the contest account; one synthetic case debugged through knowledge retrieval, proposal and evidence review.
- [x] Multi-agent controller draft created with the result-follow-up child workflow; routing and collaboration remain unverified.
- [ ] Submitted version deployed as runtime with MaaS authentication; platform API trace/screenshots captured.
- [ ] Real AgentArts 50-case report meets preregistered recall, precision, false-alert, evidence, and error gates.
- [ ] Timed participant study records paired task durations and error rates; only then claim work-time savings.
- [ ] Reachable HTTPS visual demo deployed and verified by a second device.
