# ClinLoop AgentArts contest design

## Outcome and boundaries

AgentArts hosts the workflow that proposes a clinical workflow intent from synthetic events and retrieved process knowledge. ClinLoop receives the structured proposal, checks patient and evidence references, executes read-only verification tools, persists the run, and leaves review and handoff decisions to a clinician. No agent output diagnoses, prescribes, or closes a loop by itself.

The contest demo must invoke a **published AgentArts runtime**, show the returned run provenance in ClinLoop, and demonstrate the event → intent → evidence → finding → clinician review cycle. Local DeepSeek and mock modes remain development aids, never evidence of AgentArts deployment.

## Platform workflow

1. Start node accepts `context_json` (the time-bounded `AgentContext`), `schema_version`, and an opaque `request_id`.
2. A knowledge retrieval node looks up the versioned synthetic workflow SOP, containing definitions of result follow-up, acknowledgement, and escalation. It contains no patient data or answers to evaluation cases.
3. An intent-proposal LLM node proposes a strict `AgentProposal` JSON object. It receives the context and retrieved SOP; it must cite only visible event or evidence IDs.
4. A separate evidence-review LLM node checks that the proposal corresponds to the visible event, names only allowed read-only tools, and marks uncertainty. Two LLM nodes are a role split, not by themselves a published multi-agent application.
5. The end node emits `proposal_json` as a JSON string. ClinLoop validates it and applies deterministic guard rules before persistence.

The first deployable workflow can pass the small, already visible context directly to the LLM nodes. For a tool-use demonstration, connect AgentArts HTTP nodes to the authenticated read-only ClinLoop evidence service. A cloud runtime cannot call localhost; deployment requires a reachable HTTPS endpoint. Write tools remain outside AgentArts.

A separate AgentArts multi-agent controller must invoke published intent and review child workflows or child agents for the judge-facing collaboration demo. Its actual platform trace, not the local workflow code, will substantiate the multi-agent claim.

## Evaluation contract

The primary endpoint is `RESULT_WITHOUT_ACKNOWLEDGEMENT` on a held-out synthetic, database-backed replay corpus. Report TP, FP, FN, TN, precision, recall, false-alert rate, evidence validity, provider errors, tool calls, and latency. `recall >= 0.95` is a preregistered target, never a result until a published runtime has actually run on the frozen cases. Include the full denominator and failures. Compare with the same production Worker using rules only. Do not tune on the held-out set.

Efficiency needs a separate timed, counterbalanced task study with consenting users. Measure median time to identify and verify a missing acknowledgement, missed cases, and review burden. Synthetic replay runtime alone does not establish human time savings.

## External dependency

Account access, region, published runtime name, API key, and a reachable HTTPS demo host are required for live AgentArts deployment. Keep secrets outside Git. The contest claim remains incomplete until those resources are configured and the live report is generated.
