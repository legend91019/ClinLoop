import type {
  AgentRun,
  ClinicalEvent,
  Clinician,
  EvidenceSummary,
  FindingResponse,
  HandoffResponse,
  HandoffText,
  LoopDetailResponse,
  LoopSummary,
  ReviewAction,
  ReviewResponse,
  TimelineResponse,
} from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function isClinician(actor: Clinician | null): actor is Clinician {
  return (
    !!actor?.actor_id.trim() && ['PHYSICIAN', 'CLINICIAN'].includes(actor.role)
  );
}

function actorHeaders(actor: Clinician): Record<string, string> {
  if (!isClinician(actor))
    throw new ApiError(0, '请先填写医生 ID 并选择临床角色');
  return { 'X-Actor-Id': actor.actor_id.trim(), 'X-Actor-Role': actor.role };
}

export class ApiClient {
  private prefix: string;
  constructor(
    public baseUrl = import.meta.env.VITE_API_BASE_URL ??
      'http://localhost:8000',
  ) {
    const base = baseUrl.trim().replace(/\/+$/, '');
    this.prefix = base.endsWith('/api/v1')
      ? base
      : base.endsWith('/api')
        ? `${base}/v1`
        : `${base}/api/v1`;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.prefix}${path}`, init);
    } catch (error) {
      if (
        init.signal?.aborted ||
        (error instanceof Error && error.name === 'AbortError')
      )
        throw error;
      throw new ApiError(0, '无法连接服务，请检查 API 地址和网络后重试');
    }
    const text = await response.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    if (!response.ok) {
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? body.detail
          : undefined;
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail
                .map((item) =>
                  typeof item?.msg === 'string' ? item.msg : '请求字段无效',
                )
                .join('；')
            : `服务请求失败（HTTP ${response.status}），请重试`;
      throw new ApiError(response.status, message);
    }
    if (body === null)
      throw new ApiError(response.status, '服务返回格式无效，请重试');
    return body as T;
  }

  listTimeline(patient: string, hours = 24, signal?: AbortSignal) {
    return this.request<TimelineResponse>(
      `/patients/${encodeURIComponent(patient)}/timeline?hours=${hours}`,
      { signal },
    );
  }
  listLoops(patient: string, signal?: AbortSignal) {
    return this.request<LoopSummary[]>(
      `/patients/${encodeURIComponent(patient)}/loops`,
      { signal },
    );
  }
  getLoop(id: string, signal?: AbortSignal) {
    return this.request<LoopDetailResponse>(
      `/loops/${encodeURIComponent(id)}`,
      { signal },
    );
  }
  listFindings(patient: string, signal?: AbortSignal) {
    return this.request<FindingResponse[]>(
      `/patients/${encodeURIComponent(patient)}/findings`,
      { signal },
    );
  }
  getFinding(id: string, signal?: AbortSignal) {
    return this.request<FindingResponse>(
      `/findings/${encodeURIComponent(id)}`,
      { signal },
    );
  }
  getEvidence(id: string, signal?: AbortSignal) {
    return this.request<EvidenceSummary>(
      `/evidence/${encodeURIComponent(id)}`,
      { signal },
    );
  }
  getEvidenceSource(id: string, signal?: AbortSignal) {
    return this.request<ClinicalEvent>(
      `/evidence/${encodeURIComponent(id)}/source`,
      { signal },
    );
  }
  getTrace(id: string, signal?: AbortSignal) {
    return this.request<AgentRun[]>(`/loops/${encodeURIComponent(id)}/trace`, {
      signal,
    });
  }
  listPatientRuns(patient: string, signal?: AbortSignal) {
    return this.request<AgentRun[]>(
      `/patients/${encodeURIComponent(patient)}/runs`,
      { signal },
    );
  }
  submitSyntheticNote() {
    const now = new Date().toISOString();
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    return this.request<{ event_id: string; accepted: boolean }>('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id: `EVT-DEMO-${suffix}`,
        patient_id: 'P-1001',
        encounter_id: 'ENC-2001',
        event_type: 'NOTE_CREATED',
        event_time: now,
        source_time: now,
        payload_ref: `NOTE-DEMO-${suffix}`,
        actor: {
          actor_id: 'DR-DEMO',
          role: 'PHYSICIAN',
          display_name: 'Synthetic Demo',
        },
        payload: {
          text: '今天复查血培养，结果出来后再决定下一步。',
          intent_hint: 'FOLLOW_RESULT',
          expected_evidence: ['blood_culture_result'],
          priority: 'HIGH',
        },
      }),
    });
  }
  submitSyntheticLab() {
    const now = new Date().toISOString();
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    return this.request<{ event_id: string; accepted: boolean }>('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id: `EVT-DEMO-LAB-${suffix}`,
        patient_id: 'P-1001',
        encounter_id: 'ENC-2001',
        event_type: 'LAB_RESULT_CREATED',
        event_time: now,
        source_time: now,
        payload_ref: `LAB-DEMO-${suffix}`,
        actor: {
          actor_id: 'LAB-DEMO',
          role: 'SYSTEM',
          display_name: 'Synthetic Lab',
        },
        payload: {
          panel: 'blood_culture_result',
          result: 'synthetic_positive',
        },
      }),
    });
  }
  submitSyntheticProgress(labEventId: string) {
    if (!labEventId.startsWith('EVT-DEMO-LAB-'))
      throw new ApiError(0, '请先发送本次合成血培养结果');
    const now = new Date().toISOString();
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    return this.request<{ event_id: string; accepted: boolean }>('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id: `EVT-DEMO-PROGRESS-${suffix}`,
        patient_id: 'P-1001',
        encounter_id: 'ENC-2001',
        event_type: 'PROGRESS_NOTE_CREATED',
        event_time: now,
        source_time: now,
        payload_ref: `NOTE-DEMO-PROGRESS-${suffix}`,
        actor: {
          actor_id: 'DR-DEMO',
          role: 'PHYSICIAN',
          display_name: 'Synthetic Demo',
        },
        payload: {
          text: '已查看血培养结果，继续等待药敏结果并在结果出来后复核。',
          acknowledges_event_id: labEventId,
          creates_dependency: 'susceptibility_result',
        },
      }),
    });
  }
  submitSyntheticSusceptibility() {
    const now = new Date().toISOString();
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    return this.request<{ event_id: string; accepted: boolean }>('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id: `EVT-DEMO-SUS-${suffix}`,
        patient_id: 'P-1001',
        encounter_id: 'ENC-2001',
        event_type: 'LAB_RESULT_CREATED',
        event_time: now,
        source_time: now,
        payload_ref: `LAB-DEMO-SUS-${suffix}`,
        actor: {
          actor_id: 'LAB-DEMO',
          role: 'SYSTEM',
          display_name: 'Synthetic Lab',
        },
        payload: {
          panel: 'susceptibility_result',
          result: 'synthetic_available',
        },
      }),
    });
  }
  getHandoff(id: string, signal?: AbortSignal) {
    return this.request<HandoffResponse>(`/handoff/${encodeURIComponent(id)}`, {
      signal,
    });
  }
  async reviewFinding(
    id: string,
    action: ReviewAction,
    reason: string,
    actor: Clinician,
  ) {
    const headers = actorHeaders(actor);
    if (action === 'REJECT' && !reason.trim())
      throw new ApiError(0, '驳回必须填写非空理由');
    return this.request<ReviewResponse>(
      `/findings/${encodeURIComponent(id)}/review`,
      {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        }),
      },
    );
  }
  async createHandoffDraft(
    patient: string,
    encounter: string,
    actor: Clinician,
  ) {
    const headers = actorHeaders(actor);
    if (!encounter.trim())
      throw new ApiError(0, '请明确选择或填写当前患者的就诊 ID');
    return this.request<HandoffResponse>(
      `/patients/${encodeURIComponent(patient)}/handoff/draft?encounter_id=${encodeURIComponent(encounter.trim())}`,
      { method: 'POST', headers },
    );
  }
  async updateHandoff(id: string, text: HandoffText, actor: Clinician) {
    const { situation, background, assessment, recommendation } = text;
    return this.request<HandoffResponse>(`/handoff/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { ...actorHeaders(actor), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        situation,
        background,
        assessment,
        recommendation,
      }),
    });
  }
  async sealHandoff(id: string, actor: Clinician) {
    return this.request<HandoffResponse>(
      `/handoff/${encodeURIComponent(id)}/seal`,
      { method: 'POST', headers: actorHeaders(actor) },
    );
  }
}

export const api = new ApiClient();
