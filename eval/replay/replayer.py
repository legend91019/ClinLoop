from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel

from eval.models import CasePrediction, HandlerResult, ReplayResult, SyntheticCase, VisibleContext
from eval.replay.records import observable_evidence
from packages.contracts import ClinicalEvent


class EventHandler(Protocol):
    def handle_event(self, event: ClinicalEvent, context: VisibleContext) -> HandlerResult: ...
    def final_states(self) -> dict[str, Any]: ...


def replay(case: SyntheticCase, handler: EventHandler) -> ReplayResult:
    """Dispatch chronologically at max(event_time, source_time).

    Only records already dispatched, clinically occurred, and source-recorded
    by the current event are visible. Late source records cannot leak backwards.
    The complete case and its annotation are never passed to the handler.
    """
    events = sorted(
        case.events, key=lambda e: (max(e.event_time, e.source_time), e.event_time, e.event_id)
    )
    processed = []
    runs, calls, model_calls, findings = [], [], [], []
    handoff = None
    for event in events:
        processed.append(event)
        available_at = max(event.event_time, event.source_time)
        visible = [
            e for e in processed if e.event_time <= available_at and e.source_time <= available_at
        ]
        evidence = [observable_evidence(e) for e in visible]
        context = VisibleContext(
            patient_id=case.patient_id,
            as_of=available_at,
            available_at=available_at,
            events=visible,
            evidence=evidence,
        ).model_copy(deep=True)
        output = handler.handle_event(event.model_copy(deep=True), context)
        output = HandlerResult.model_validate(output).model_copy(deep=True)
        runs.extend(output.runs)
        calls.extend(output.tool_calls)
        model_calls.extend(output.model_calls)
        findings.extend(output.findings)
        if output.handoff is not None:
            handoff = output.handoff
    return ReplayResult(
        patient_id=case.patient_id,
        event_ids=[e.event_id for e in events],
        runs=runs,
        tool_calls=calls,
        model_calls=model_calls,
        prediction=CasePrediction(patient_id=case.patient_id, findings=findings, handoff=handoff),
        final_states=handler.final_states(),
    )


def canonicalize(value: Any) -> Any:
    """Alpha-rename runtime UUIDs, preserving referential equality and chronology.

    Drop runtime timestamps/durations, keep event_time, source_time, observed_at,
    detected_at and all semantic IDs. The raw replay still keeps full run traces.
    """
    runtime_ids: dict[str, str] = {}
    uuid_shape = re.compile(
        r"(?:RUN|STEP|FND|LOOP|INTENT|HOF|AUD)-[0-9a-f]{12}|[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
        re.IGNORECASE,
    )
    runtime_fields = {
        "run_id",
        "source_run_id",
        "resumed_from_run_id",
        "step_id",
        "finding_id",
        "finding_ids",
        "loop_id",
        "intent_id",
        "handoff_id",
        "audit_id",
    }
    clinical_fields = {
        "event_id",
        "event_ids",
        "trigger_event_id",
        "source_event_id",
        "payload_ref",
        "source_id",
        "evidence_id",
        "evidence_ids",
        "supporting_evidence",
        "patient_id",
        "encounter_id",
        "case_id",
        "item_id",
        "item_ids",
        "actor_id",
    }
    candidates, clinical_ids = set(), set()

    def materialize(obj):
        if isinstance(obj, BaseModel):
            return materialize(obj.model_dump(mode="json"))
        if isinstance(obj, dict):
            return {k: materialize(v) for k, v in obj.items()}
        if isinstance(obj, (tuple, list)):
            return [materialize(v) for v in obj]
        return obj

    data = materialize(value)

    def identify(obj):
        if isinstance(obj, dict):
            for field, child in obj.items():
                identifiers = child if isinstance(child, list) else [child]
                if field in runtime_fields:
                    candidates.update(
                        i for i in identifiers if isinstance(i, str) and uuid_shape.fullmatch(i)
                    )
                elif field in clinical_fields:
                    clinical_ids.update(i for i in identifiers if isinstance(i, str))
                identify(child)
        elif isinstance(obj, list):
            for child in obj:
                identify(child)

    identify(data)
    # A UUID's shape does not establish its role. Rename only IDs identified
    # by runtime fields, and let clinical provenance win in any ambiguous case.
    identified = candidates - clinical_ids
    pattern = (
        re.compile(
            r"(?<![\w-])(?:"
            + "|".join(re.escape(i) for i in sorted(identified, key=lambda i: (-len(i), i)))
            + r")(?![\w-])"
        )
        if identified
        else None
    )
    ignored = {
        "started_at",
        "finished_at",
        "duration_ms",
        "created_at",
        "updated_at",
        "ingested_at",
    }

    def rename(match):
        ident = match.group(0)
        if ident not in runtime_ids:
            runtime_ids[ident] = f"runtime:{len(runtime_ids) + 1}"
        return runtime_ids[ident]

    def visit(obj):
        if isinstance(obj, dict):
            # Runtime-keyed memory maps retain creation order, rather than
            # sorting on random UUID text. Canonicalize keys as well as values
            # so loop/run references retain their identity relationships.
            keys = sorted(k for k in obj if k not in identified)
            keys.extend(k for k in obj if k in identified)
            return {
                (pattern.sub(rename, k) if pattern else k): visit(obj[k])
                for k in keys
                if k not in ignored
            }
        if isinstance(obj, (tuple, list)):
            return [visit(item) for item in obj]
        if isinstance(obj, str):
            return pattern.sub(rename, obj) if pattern else obj
        return obj

    return visit(data)
