"""Run the canonical synthetic ClinLoop event trajectory.

The demo deliberately uses the same ports as the API and worker: events are
published to an in-memory bus, handled by :class:`WorkflowAgent`, and then
written through the API repositories.  That keeps the command useful without
Docker while preserving the production boundaries between contracts, worker
execution and database writes.

Usage::

    python scripts/run_demo.py --patient P-1001
    python scripts/run_demo.py --patient P-1001 --no-review
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Engine

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.repositories import (
    AgentRunRepository as DbAgentRunRepository,
)
from apps.api.app.repositories import (
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
)
from apps.api.app.services.handoff_service import create_draft, seal_handoff
from apps.api.app.services.review_service import review_finding
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.bus import InMemoryEventBus
from packages.contracts import ActorRef, ClinicalEvent, ReviewAction
from packages.fixtures import case_by_id, events_for_case
from packages.fixtures.seed import FIXTURE_FINDING_ID, seed_demo_case

DEMO_ACTOR = ActorRef(actor_id="DR-DEMO", role="PHYSICIAN", display_name="Demo Clinician")


def _event_run(agent: WorkflowAgent, event: ClinicalEvent, *, index: int):
    """Route each fixture beat through the worker's lifecycle seam.

    A result resumes the original result loop, the progress note resumes the
    dependency loop, and the other beats begin a normal run.  This mirrors the
    event router while remaining deterministic for the synthetic case.
    """
    if index == 1:
        return agent.resume_loop("LOOP-1001", event)
    if index == 2:
        return agent.resume_loop("LOOP-1002", event)
    return agent.handle_event(event)


def _persist_run(session, run, agent: WorkflowAgent, patient_id: str) -> tuple[Any, list[str]]:
    """Persist one worker run and map generated findings to durable records."""
    runs_repo = DbAgentRunRepository(session)
    existing_run = runs_repo.get_for_trigger(run.trigger_event_id)
    if existing_run is not None:
        return existing_run, list(existing_run.finding_ids)

    finding_ids: list[str] = []
    finding_repo = FindingRepository(session)
    for finding_id in run.finding_ids:
        finding = agent.findings.get(finding_id)
        if finding is None or finding.patient_id != patient_id:
            continue
        # The fixture already contains the canonical finding. Reusing it keeps
        # repeated demo runs idempotent while retaining the worker's evidence.
        existing = next(
            (
                candidate
                for candidate in finding_repo.list_for_patient(patient_id)
                if candidate.finding_type is finding.finding_type
                and set(candidate.supporting_evidence) & set(finding.supporting_evidence)
            ),
            None,
        )
        if existing is None:
            finding_repo.add(finding)
            finding_ids.append(finding.finding_id)
        else:
            finding_ids.append(existing.finding_id)

    persisted_run = run.model_copy(update={"finding_ids": finding_ids})
    runs_repo.create(persisted_run)
    from apps.api.app.repositories import AuditRepository

    AuditRepository(session).append(
        entity_type="agent_run",
        entity_id=persisted_run.run_id,
        action="run",
        actor=DEMO_ACTOR,
        source_run_id=persisted_run.run_id,
        payload={
            "patient_id": patient_id,
            "trigger_event_id": persisted_run.trigger_event_id,
            "finding_ids": finding_ids,
        },
    )
    return persisted_run, finding_ids


def _load_events(session, events: Iterable[ClinicalEvent]) -> list[ClinicalEvent]:
    repo = ClinicalEventRepository(session)
    loaded: list[ClinicalEvent] = []
    for event in events:
        if repo.get(event.event_id) is None:
            repo.add(event)
        loaded.append(event)
    return loaded


def run_demo(
    patient_id: str,
    *,
    engine: Engine | None = None,
    auto_review: bool = True,
    ensure_schema: bool = False,
) -> dict[str, Any]:
    """Execute the four-beat synthetic trajectory and return JSON-safe data.

    ``auto_review`` is enabled for the CLI so the complete demo ends with a
    sealed handoff. Tests and operators can disable it to inspect the safety
    boundary where pending findings cannot be sealed or resolved.
    """
    case = case_by_id("CASE-BLOOD-CULTURE")
    if patient_id != case.patient_id:
        raise ValueError(f"unknown demo patient: {patient_id}")
    db_engine = engine or build_engine()
    if ensure_schema:
        create_schema(db_engine)

    events = events_for_case(case)
    bus = InMemoryEventBus()
    agent = WorkflowAgent()
    event_rows: list[dict[str, Any]] = []
    all_finding_ids: list[str] = []

    with session_scope(db_engine) as session:
        seed_demo_case(session)
        # Hydrate the worker's minimal context from durable fixture facts. The
        # Agent then resumes the same loop IDs the API and console display.
        for intent in ClinicalIntentRepository(session).list_for_patient(patient_id):
            agent.memory.save_intent(intent)
        for loop in LoopRepository(session).list_for_patient(patient_id):
            agent.memory.save_loop(loop)
        for evidence in EvidenceRepository(session).list_for_patient(patient_id):
            agent.memory.append_evidence(evidence, loop_id=None)
        loaded_events = _load_events(session, events)
        for index, event in enumerate(loaded_events):
            bus.publish(event)
            queued = bus.consume(count=1)
            if not queued:
                raise RuntimeError(f"event was not delivered: {event.event_id}")
            run = _event_run(agent, queued[0], index=index)
            persisted_run, finding_ids = _persist_run(session, run, agent, patient_id)
            all_finding_ids.extend(finding_ids)
            event_rows.append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "run_id": persisted_run.run_id,
                    "loop_id": persisted_run.loop_id,
                    "stop_reason": persisted_run.stop_reason.value
                    if persisted_run.stop_reason
                    else None,
                    "finding_ids": finding_ids,
                }
            )

        # Keep the worker's generated evidence visible to the durable finding
        # while retaining the fixture's stable canonical identifier.
        all_finding_ids = list(dict.fromkeys([FIXTURE_FINDING_ID, *all_finding_ids]))
        handoff = create_draft(session, patient_id, case.encounter_id, DEMO_ACTOR)
        final_action = "DRAFT_PENDING_REVIEW"
        if auto_review:
            for finding_id in all_finding_ids:
                finding = FindingRepository(session).get(finding_id)
                if finding is not None and finding.requires_review:
                    review_finding(
                        session,
                        finding_id,
                        ReviewAction.ACCEPT,
                        DEMO_ACTOR,
                        reason="Reviewed during the synthetic integration demo.",
                    )
            handoff = seal_handoff(session, handoff.handoff_id, DEMO_ACTOR)
            final_action = "SEALED_AFTER_REVIEW"

        loops = LoopRepository(session).list_for_patient(patient_id)
        persisted_findings = [FindingRepository(session).get(fid) for fid in all_finding_ids]
        return {
            "patient_id": patient_id,
            "case_id": case.case_id,
            "events": event_rows,
            "run_ids": [item["run_id"] for item in event_rows],
            "loop_ids": [loop.loop_id for loop in loops],
            "findings": [
                {
                    "finding_id": finding.finding_id,
                    "finding_type": finding.finding_type.value,
                    "supporting_evidence": finding.supporting_evidence,
                    "review_status": finding.review_status,
                }
                for finding in persisted_findings
                if finding is not None
            ],
            "handoff_id": handoff.handoff_id,
            "final_action": final_action,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient", required=True, help="synthetic patient id, e.g. P-1001")
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL (defaults to DATABASE_URL or the local Postgres URL)",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="leave the handoff draft pending review instead of sealing it",
    )
    args = parser.parse_args(argv)
    try:
        result = run_demo(
            args.patient,
            engine=build_engine(args.database_url),
            auto_review=not args.no_review,
            ensure_schema=True,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    for event in result["events"]:
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
