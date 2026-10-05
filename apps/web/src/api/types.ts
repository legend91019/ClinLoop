export interface Actor {
  actor_id: string;
  role: string;
  display_name?: string | null;
}
export interface Clinician {
  actor_id: string;
  role: 'PHYSICIAN' | 'CLINICIAN';
}
export interface TimelineEntry {
  event_id: string;
  event_type: string;
  event_time: string;
  source_time: string;
  actor: Actor;
  payload_ref: string;
}
export interface TimelineResponse {
  patient_id: string;
  hours: number;
  window_start: string;
  window_end: string;
  count: number;
  entries: TimelineEntry[];
}
export interface ClinicalEvent extends TimelineEntry {
  patient_id: string;
  encounter_id: string;
  payload: Record<string, unknown>;
  ingested_at: string;
}
export interface LoopSummary {
  loop_id: string;
  intent_id: string;
  goal: string;
  state: string;
  waiting_for: string[];
  depends_on: string[];
  owner: string | null;
  priority: string;
  confidence: number;
  next_check_at: string | null;
}
export interface FindingResponse {
  finding_id: string;
  patient_id: string;
  loop_id: string | null;
  intent_id: string | null;
  finding_type: string;
  claim: string;
  supporting_evidence: string[];
  searched_sources: string[];
  confidence: number;
  requires_review: boolean;
  review_status: string;
  detected_at: string;
}
export interface EvidenceSummary {
  evidence_id: string;
  source_type: string;
  source_id: string;
  observed_at: string;
  claim: string;
  trust_level: string;
}
export interface LoopDetailResponse {
  loop: LoopSummary;
  intent: {
    intent_id: string;
    intent_type: string;
    text: string;
    expected_evidence: string[];
    requires_clinician_review: boolean;
  } | null;
  evidence: EvidenceSummary[];
  findings: string[];
}
export type ReviewAction = 'ACCEPT' | 'REJECT';
export interface ReviewResponse {
  decision_id: string;
  finding_id: string;
  action: string;
  review_status: string;
}
export interface ToolCall {
  tool_name: string;
  arguments: Record<string, unknown>;
  result_ref: string | null;
  ok: boolean;
  error_code: string | null;
  duration_ms: number | null;
  started_at: string | null;
}
export interface AgentStep {
  step_id: string;
  kind: string;
  input_ref: string | null;
  output_ref: string | null;
  reason: string;
  tool_call?: ToolCall | null;
  started_at: string | null;
  finished_at: string | null;
}
export interface AgentRun {
  run_id: string;
  loop_id: string | null;
  intent_id: string | null;
  trigger_event_id: string;
  steps: AgentStep[];
  tool_calls: ToolCall[];
  stop_reason: string | null;
}
export interface HandoffText {
  situation: string;
  background: string;
  assessment: string;
  recommendation: string;
}
export interface HandoffResponse extends HandoffText {
  handoff_id: string;
  patient_id: string;
  encounter_id: string;
  status: string;
  loop_ids: string[];
  evidence_ids: string[];
  pending_items: string[];
  confirmed_items: string[];
}
