export interface PatientProfile {
  patient_id: string;
  encounter_id: string;
  display_name: string;
  sex: '男' | '女' | '未说明';
  age: number;
  ethnicity?: string;
  marital_status?: '未记录' | '未婚' | '已婚' | '离异' | '丧偶' | '其他';
  birthplace?: string;
  occupation?: string;
  ward: string;
  bed: string;
  chief_complaint: string;
  history: string;
  allergies: string;
  admitted_at: string | null;
  synthetic: boolean;
  open_tasks: number;
}

export type PatientCreate = Omit<
  PatientProfile,
  'patient_id' | 'encounter_id' | 'admitted_at' | 'synthetic' | 'open_tasks'
> & { admitted_at?: string | null };
export type DocumentKind = 'ADMISSION' | 'ROUND' | 'PROGRESS';
export type DraftMode = 'CLINICAL' | 'DEMO';
export interface ClinicalDocument {
  document_id: string;
  patient_id: string;
  encounter_id: string;
  kind: DocumentKind;
  title: string;
  content: string;
  status: 'DRAFT' | 'SUBMITTED';
  revision: number;
  author_id: string;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  event_id: string | null;
  generation?: {
    source_text: string;
    interview_id: string;
    provider: string;
    model: string;
    lab_sources?: unknown[];
    writing_version?: number;
    draft_mode?: DraftMode;
    sources?: {
      source_id: string;
      label: string;
      text: string;
      ref?: string;
    }[];
    clinical_sections?: {
      heading: string;
      sentences: { text: string; source_ids: string[] }[];
    }[];
    missing_information?: string[];
    conflicts?: { text: string; source_ids: string[] }[];
  } | null;
  signature?: { name: string; actor_id: string; signed_at: string } | null;
}

export interface Interview {
  interview_id: string;
  transcript: string;
  kind: DocumentKind;
  saved_at: string;
  generation: {
    status: 'QUEUED' | 'READY' | 'FAILED';
    error?: string;
    provider?: string;
    draft_mode?: DraftMode;
  };
  document: ClinicalDocument | null;
}
export interface FirstRoundStatus {
  state: 'PENDING' | 'OVERDUE' | 'COMPLETED' | 'UNSCHEDULED';
  due_at: string | null;
  document_id: string | null;
  completed_late: boolean;
}

export interface ManagedTask {
  loop_id: string;
  patient_id: string;
  encounter_id: string;
  goal: string;
  state: string;
  priority: string;
  owner: string | null;
  due_at: string | null;
  source_document_id: string | null;
  system_managed?: boolean;
  history: {
    action: string;
    actor_id: string;
    reason: string | null;
    created_at: string;
  }[];
}

export interface AgentCandidate {
  candidate_id: string;
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED';
  source_text: string;
  proposal: {
    goal: string;
    rationale: string;
    intent_type: string;
    priority: string;
    confidence: number;
    expected_evidence: string[];
  };
  loop_id: string | null;
  review_reason: string;
}
export interface AgentWorkspace {
  provider: string;
  documents: {
    document_id: string;
    title: string;
    analysis: null | {
      status: 'QUEUED' | 'READY' | 'FAILED';
      event_id: string;
      run_id: string | null;
      provider?: string;
      model?: string;
      error?: string | null;
      candidates: AgentCandidate[];
    };
  }[];
  tasks: {
    loop_id: string;
    goal: string;
    state: string;
    priority: string;
    source_document_id: string | null;
    evidence_id: string | null;
    result: import('./types').ClinicalEvent | null;
  }[];
}
