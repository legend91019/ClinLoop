export type CareMode = 'PREPARE' | 'QUALITY' | 'PLAN';
export type RoundPreparation = {
  last_round_at: string | null;
  new_labs: { id: string; label: string; text: string; time: string }[];
  open_tasks: {
    id: string;
    label: string;
    state: string;
    due_at: string | null;
  }[];
  last_round: { id: string; label: string; text: string; time: string } | null;
  limits: Record<string, boolean>;
};
export type CareTask = {
  key: string;
  goal: string;
  source_quote: string;
  source_ids: string[];
  depends_on: string[];
  condition: 'NONE' | 'RESULT' | 'CLARIFY';
  panel: string;
  question: string;
  due_at: string | null;
  existing_loop_id: string | null;
};
export type CareRun = {
  run_id: string;
  mode: CareMode;
  document_id: string | null;
  status: 'QUEUED' | 'RUNNING' | 'READY' | 'FAILED' | 'ACTIVE';
  revision: number;
  stale: boolean;
  created_at: string;
  provider?: string;
  model?: string;
  error?: string;
  clarification?: string;
  result?: {
    summary: string;
    findings: { category: string; text: string; source_ids: string[] }[];
    tasks: CareTask[];
  };
  sources?: { id: string; label: string; text: string; time?: string }[];
  trace: { tool: string; reason: string; count: number; time: string }[];
  history: { time: string; actor: string; reason: string }[];
  reviews?: Record<string, { action: string; reason: string; actor: string }>;
  bindings?: Record<string, string>;
  task_states?: Record<
    string,
    { state: string; message: string; overdue: boolean; result_ids: string[] }
  >;
};
export type CareDecision = {
  revision: number;
  action: 'ACCEPT' | 'UPDATE' | 'RESOLVE' | 'DISMISS';
  reason: string;
  item_key?: string;
  tasks?: CareTask[];
};
