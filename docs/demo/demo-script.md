# Demo narration

1. Start at the patient timeline and show the ward-round note requesting a
   repeat blood culture.
2. Open the blood-culture result. The console shows the workflow gap and the
   source pointer `LAB-8821`; this is an evidence-backed continuity warning,
   not a diagnosis or treatment recommendation.
3. Open Agent Trace and show the `OBSERVE → REASON → PLAN → ACT → VERIFY`
   steps and the `REQUIRES_CLINICIAN_REVIEW` stop reason.
4. Show the susceptibility loop under Open Loops. It remains `WAITING_EVENT`
   and depends on `LOOP-1001`.
5. Generate the handoff draft, review the finding as the synthetic clinician,
   and seal the draft. Point out the appended `run`, `review`, and `seal`
   audit entries.
