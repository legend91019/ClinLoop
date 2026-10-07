# Guided Agent trial design

## Goal

After a synthetic event is accepted, show when its specific Agent run has been persisted and refresh the patient views automatically. Keep the existing manual refresh control for recovery.

## Flow

The four fixed buttons remain restricted to synthetic patient `P-1001`. After a successful event POST, the panel polls the existing patient-runs read endpoint for a run whose `trigger_event_id` matches the returned event ID. It waits for a terminal `stop_reason` before declaring processing complete. On completion, the parent refreshes timeline, loops, findings, and the trace panel. Buttons remain disabled while an event is being sent or processed, so each step happens in order. Model errors are shown using the stored safe error code. A timeout or API read error explains that the event was accepted but Worker status could not be confirmed.

Polling is bounded to 45 seconds and uses an abort signal. Changing patient or leaving the page cancels the wait; stale responses cannot refresh another patient's workspace. The panel does not ask for credentials or submit non-synthetic data.

## Acceptance

- Unit tests prove a matching persisted run completes polling, unrelated runs do not, timeout is bounded, and abort cancels.
- A component test proves event submission causes automatic patient view refresh after its matching run appears.
- A model error and a timeout are visibly different from successful processing.
- Existing synthetic event ordering and cross-patient protections remain intact.
