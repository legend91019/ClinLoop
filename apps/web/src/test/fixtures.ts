import type {
  AgentRun,
  ClinicalEvent,
  EvidenceSummary,
  FindingResponse,
  HandoffResponse,
  LoopSummary,
  TimelineResponse,
} from '../api/types';

export const timestamp = '2026-10-04T14:30:00+08:00';
export const timeline: TimelineResponse = {
  patient_id: 'P-1001',
  hours: 24,
  window_start: '2026-10-03T20:00:00+08:00',
  window_end: '2026-10-04T20:00:00+08:00',
  count: 1,
  entries: [
    {
      event_id: 'EVT-LAB',
      event_type: 'LAB_RESULT_CREATED',
      event_time: timestamp,
      source_time: timestamp,
      actor: { actor_id: 'LAB-SYS', role: 'SYSTEM', display_name: '检验系统' },
      payload_ref: 'LAB-8821',
    },
  ],
};
export const loop: LoopSummary = {
  loop_id: 'LOOP-1',
  intent_id: 'INT-1',
  goal: '追踪血培养结果与医生响应',
  state: 'PENDING_REVIEW',
  waiting_for: ['PROGRESS_NOTE_CREATED'],
  depends_on: [],
  owner: 'DR-8',
  priority: 'HIGH',
  confidence: 0.95,
  next_check_at: '2026-10-04T18:00:00+08:00',
};
export const finding: FindingResponse = {
  finding_id: 'FIND-1',
  patient_id: 'P-1001',
  loop_id: 'LOOP-1',
  intent_id: 'INT-1',
  finding_type: 'RESULT_WITHOUT_ACKNOWLEDGEMENT',
  claim: '血培养结果已返回，检索范围内未找到医生确认记录',
  supporting_evidence: ['EVI-1'],
  searched_sources: ['LABS', 'PROGRESS_NOTES'],
  confidence: 0.95,
  requires_review: true,
  review_status: 'PENDING_REVIEW',
  detected_at: timestamp,
};
export const evidence: EvidenceSummary = {
  evidence_id: 'EVI-1',
  source_type: 'LABS',
  source_id: 'LAB-8821',
  observed_at: timestamp,
  claim: '血培养阳性',
  trust_level: 'PATIENT_REPORTED',
};
export const source: ClinicalEvent = {
  ...timeline.entries[0],
  patient_id: 'P-1001',
  encounter_id: 'ENC-REAL-9',
  payload: {
    test: 'blood_culture',
    result: 'positive',
    raw_note: '合成原始检验记录',
  },
  ingested_at: timestamp,
};
export const handoff: HandoffResponse = {
  handoff_id: 'HAND-1',
  patient_id: 'P-1001',
  encounter_id: 'ENC-REAL-9',
  status: 'DRAFT',
  situation: '当前情况',
  background: '既往背景',
  assessment: '流程评估',
  recommendation: '待跟进事项',
  loop_ids: ['LOOP-1'],
  evidence_ids: ['EVI-1'],
  pending_items: ['等待医生审核血培养结果'],
  confirmed_items: ['已确认合成事实'],
};
export const tool = {
  tool_name: 'get_labs',
  arguments: { patient_id: 'P-1001', marker: 'ACT-SECRET-ARG' },
  result_ref: 'LAB-8821',
  ok: true,
  error_code: null,
  duration_ms: 12,
  started_at: timestamp,
};
export const runs: AgentRun[] = [
  {
    run_id: 'RUN-1',
    loop_id: 'LOOP-1',
    intent_id: 'INT-1',
    trigger_event_id: 'EVT-LAB',
    steps: [
      {
        step_id: 'STEP-1',
        kind: 'ACT',
        input_ref: 'EVT-LAB',
        output_ref: 'LAB-8821',
        reason: '读取检验结果并绑定来源',
        tool_call: tool,
        started_at: timestamp,
        finished_at: timestamp,
      },
    ],
    tool_calls: [tool],
    stop_reason: 'REQUIRES_CLINICIAN_REVIEW',
  },
];
