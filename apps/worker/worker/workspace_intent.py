"""Conservative deterministic proposal support for the explicitly labelled local demo."""

import re

from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from packages.contracts import EventType, IntentType
from packages.contracts.workspace_agent import PANELS


def demo_document_proposal(context: AgentContext) -> AgentProposal:
    text = str(context.event.payload.get("text", ""))
    base = dict(
        patient_id=context.event.patient_id,
        goal=text,
        rationale="本地确定性规则从这段原文识别待办，需医生确认；未调用真实模型。",
        confidence=0.8,
        evidence_refs=[context.event.event_id],
    )
    if re.search(r"无需|不必|不用|不需要|取消|已完成|已补充|已核对|已查看", text):
        return AgentProposal(**base, intent_type=None)
    if not re.search(r"跟进|随访|等待|待查|待回报|关注|复查|补充|核对|整理|通知|提醒|完善", text):
        return AgentProposal(**base, intent_type=None)
    for panel, name in PANELS.items():
        if name in text and re.search(r"结果|报告|复查|等待|跟进|关注|回报|提醒|通知", text):
            return AgentProposal(
                **base,
                intent_type=IntentType.FOLLOW_RESULT,
                expected_evidence=[panel],
                waiting_for=[EventType.LAB_RESULT_CREATED],
                priority="HIGH",
            )
    if re.search(r"(?:补充|核对|整理|完善|跟进|随访).{2,}", text) and len(text) >= 5:
        return AgentProposal(**base, intent_type=IntentType.UPDATE_PLAN, priority="NORMAL")
    return AgentProposal(**base, intent_type=None)
