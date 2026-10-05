# Sample output

The run IDs below are examples; runtime IDs are generated per execution.

```json
{
  "patient_id": "P-1001",
  "events": [
    {"event_id": "EVT-1001", "loop_id": "LOOP-1001"},
    {"event_id": "EVT-1002", "loop_id": "LOOP-1001", "finding_ids": ["FND-..."]},
    {"event_id": "EVT-1003", "loop_id": "LOOP-1002"},
    {"event_id": "EVT-1004", "loop_id": null}
  ],
  "loop_ids": ["LOOP-1001", "LOOP-1002"],
  "final_action": "SEALED_AFTER_REVIEW"
}
```
