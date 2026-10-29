import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AgentWorkspace, PatientProfile } from '../api/workspaceTypes';
import { json, serve } from '../test/server';
import PatientAgentPanel from './PatientAgentPanel';

const patient: PatientProfile = {
  patient_id: 'P-2001',
  encounter_id: 'ENC-3001',
  display_name: '模拟患者',
  sex: '女',
  age: 34,
  ward: '模拟病区',
  bed: '01',
  chief_complaint: '',
  history: '',
  allergies: '',
  admitted_at: null,
  synthetic: true,
  open_tasks: 0,
};
const actor = { actor_id: 'DR-TEST', role: 'PHYSICIAN' as const };
function snapshot(): AgentWorkspace {
  return {
    provider: 'mock',
    tasks: [],
    documents: [
      {
        document_id: 'DOC-AGENT',
        title: '查房随访',
        analysis: {
          status: 'READY',
          event_id: 'EVT-ROUND',
          run_id: 'RUN-ANALYSIS',
          provider: 'deterministic-mock',
          model: 'mock',
          candidates: [
            {
              candidate_id: 'CAND-1',
              status: 'PENDING',
              source_text: '血培养结果出来后提醒我查看',
              proposal: {
                goal: '跟进血培养结果',
                rationale: '从原文识别随访意图',
                intent_type: 'FOLLOW_RESULT',
                priority: 'HIGH',
                confidence: 0.8,
                expected_evidence: ['blood_culture_result'],
              },
              loop_id: null,
              review_reason: '',
            },
          ],
        },
      },
    ],
  };
}

describe('patient workflow agent', () => {
  it('shows provenance and creates tasks only after an explicit candidate approval', async () => {
    const data = snapshot();
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/agent-workspace')) return json(data);
      if (r.url.pathname.endsWith('/review')) {
        data.documents[0].analysis!.candidates[0].status = 'ACCEPTED';
        return json({ status: 'ACCEPTED' });
      }
      return undefined;
    });
    render(
      <PatientAgentPanel
        profile={patient}
        actor={actor}
        revision={0}
        onChanged={vi.fn()}
      />,
    );
    await screen.findByText('原文：血培养结果出来后提醒我查看');
    expect(
      screen.getByText('本地确定性演示 · 未调用大模型'),
    ).toBeInTheDocument();
    expect(requests.every((r) => r.method === 'GET')).toBe(true);
    await userEvent.click(
      screen.getByRole('button', { name: '确认并创建任务' }),
    );
    await waitFor(() =>
      expect(requests.some((r) => r.method === 'POST')).toBe(true),
    );
    const request = requests.find((r) => r.method === 'POST')!;
    expect(request.url.pathname).toBe(
      '/api/v1/patients/P-2001/documents/DOC-AGENT/candidates/CAND-1/review',
    );
    expect(request.body).toMatchObject({ action: 'ACCEPT' });
    expect(request.headers.get('X-Actor-Id')).toBe('DR-TEST');
  });

  it('requires a reason to reject and disables approval without a doctor identity', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/agent-workspace')
        ? json(snapshot())
        : undefined,
    );
    const view = render(
      <PatientAgentPanel
        profile={patient}
        actor={null}
        revision={0}
        onChanged={vi.fn()}
      />,
    );
    expect(
      await screen.findByRole('button', { name: '确认并创建任务' }),
    ).toBeDisabled();
    view.rerender(
      <PatientAgentPanel
        profile={patient}
        actor={actor}
        revision={0}
        onChanged={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '驳回建议' }));
    expect(screen.getByRole('button', { name: '确认驳回' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('驳回原因'), {
      target: { value: '本次无需重复跟进' },
    });
    expect(screen.getByRole('button', { name: '确认驳回' })).toBeEnabled();
  });

  it('shows a source-backed result and submits the clinician acknowledgement with a dependency', async () => {
    const data = snapshot();
    data.documents = [];
    data.tasks = [
      {
        loop_id: 'LOOP-RESULT',
        goal: '跟进血培养',
        state: 'RESULT_AVAILABLE',
        priority: 'HIGH',
        source_document_id: 'DOC-AGENT',
        evidence_id: 'EVI-LAB',
        result: {
          event_id: 'EVT-LAB',
          patient_id: 'P-2001',
          encounter_id: 'ENC-3001',
          event_type: 'LAB_RESULT_CREATED',
          event_time: '2026-10-26T10:00:00Z',
          source_time: '2026-10-26T10:00:00Z',
          payload_ref: 'LAB-REF',
          actor: { actor_id: 'LAB', role: 'SYSTEM' },
          payload: { panel: 'blood_culture_result', result: '模拟报告已回报' },
          ingested_at: '2026-10-26T10:00:00Z',
        },
      },
    ];
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/agent-workspace')) return json(data);
      if (r.url.pathname.endsWith('/acknowledge'))
        return json({ event_id: 'EVT-ACK', accepted: true });
      return undefined;
    });
    render(
      <PatientAgentPanel
        profile={patient}
        actor={actor}
        revision={0}
        onChanged={vi.fn()}
      />,
    );
    await screen.findByText('证据引用：EVI-LAB');
    await userEvent.click(
      screen.getByRole('button', { name: '确认并继续跟进药敏' }),
    );
    const form = screen.getByLabelText('医生处理说明').closest('form')!;
    expect(
      within(form).getByRole('button', { name: '确认提交处理结果' }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText('医生处理说明'), {
      target: { value: '已查看原始报告，继续跟进药敏' },
    });
    await userEvent.click(
      within(form).getByRole('button', { name: '确认提交处理结果' }),
    );
    await waitFor(() =>
      expect(
        requests.some((r) => r.url.pathname.endsWith('/acknowledge')),
      ).toBe(true),
    );
    expect(
      requests.find((r) => r.url.pathname.endsWith('/acknowledge'))?.body,
    ).toEqual({
      reason: '已查看原始报告，继续跟进药敏',
      next_panel: 'susceptibility_result',
    });
  });
});
