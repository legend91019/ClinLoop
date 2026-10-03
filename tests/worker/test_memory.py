from __future__ import annotations

from apps.worker.worker.memory import WorkflowMemory
from packages.contracts import EvidenceNode, LoopState, OpenLoop
from packages.fixtures import MAIN_ENCOUNTER_ID, MAIN_PATIENT_ID


def test_loop_context_includes_evidence_saved_for_that_loop() -> None:
    memory = WorkflowMemory()
    loop = OpenLoop(
        loop_id="LOOP-1",
        patient_id=MAIN_PATIENT_ID,
        encounter_id=MAIN_ENCOUNTER_ID,
        intent_id="INT-1",
        goal="Follow the result",
        state=LoopState.CREATED,
    )
    memory.save_loop(loop)
    evidence = EvidenceNode(
        evidence_id="EVD-1",
        patient_id=MAIN_PATIENT_ID,
        encounter_id=MAIN_ENCOUNTER_ID,
        source_type="LABS",
        source_id="LAB-1",
        observed_at=loop.created_at,
        claim="positive",
    )

    memory.append_evidence(evidence, loop_id=loop.loop_id)

    assert [
        item.evidence_id for item in memory.get_context(MAIN_PATIENT_ID, loop.loop_id).evidence
    ] == ["EVD-1"]
