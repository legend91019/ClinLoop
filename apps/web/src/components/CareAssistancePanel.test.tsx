import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CareAssistancePanel from './CareAssistancePanel';
import { serve, json } from '../test/server';
import type { PatientProfile } from '../api/workspaceTypes';
import type { CareRun } from '../api/careTypes';

const profile = {
  patient_id: 'P-CARE',
  encounter_id: 'ENC-CARE',
} as PatientProfile;
const actor = { actor_id: 'DR-CARE', role: 'PHYSICIAN' as const };
const ready: CareRun = {
  run_id: 'CARE-1',
  mode: 'QUALITY',
  document_id: 'DOC-1',
  status: 'READY',
  revision: 2,
  created_at: '2026-11-03T08:00:00Z',
  stale: false,
  trace: [],
  history: [],
  result: {
    summary: '待核实一项',
    findings: [
      { category: 'OMISSION', text: '复查安排可能遗漏', source_ids: ['T1'] },
    ],
    tasks: [],
  },
  sources: [{ id: 'T1', label: '医生原话', text: '医生：明日复查。' }],
};

describe('care assistance', () => {
  it('automatically prepares on entry and sends scoped physician identity', async () => {
    const requests = serve();
    render(
      <CareAssistancePanel profile={profile} actor={actor} mode="PREPARE" />,
    );
    await waitFor(() =>
      expect(
        requests.some((r) => r.method === 'POST' && r.body?.mode === 'PREPARE'),
      ).toBe(true),
    );
    const request = requests.find((r) => r.method === 'POST')!;
    expect(request.body?.encounter_id).toBe('ENC-CARE');
    expect(request.headers.get('X-Actor-Id')).toBe('DR-CARE');
    expect(
      await screen.findByRole('button', { name: '等待后台处理' }),
    ).toBeDisabled();
  });
  it('shows original sources and submits a reasoned review with revision', async () => {
    const requests = serve((r) => {
      if (r.method === 'GET' && r.url.pathname.endsWith('/care-assistance'))
        return json([ready]);
      if (r.url.pathname.endsWith('/decision'))
        return json({ ...ready, revision: 3 });
    });
    render(
      <CareAssistancePanel
        profile={profile}
        actor={actor}
        mode="QUALITY"
        documentId="DOC-1"
      />,
    );
    await screen.findByText('复查安排可能遗漏', { exact: false });
    expect(screen.getByText('医生：明日复查。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '已核实并记录' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('核实或不采纳的说明'), {
      target: { value: '已对照原文核实' },
    });
    fireEvent.click(screen.getByRole('button', { name: '已核实并记录' }));
    await waitFor(() =>
      expect(requests.some((r) => r.body?.action === 'RESOLVE')).toBe(true),
    );
    expect(
      requests.find((r) => r.body?.action === 'RESOLVE')?.body,
    ).toMatchObject({ revision: 2, item_key: '0', reason: '已对照原文核实' });
  });
  it('blocks stale reviews and does not analyze unsaved edits', async () => {
    const requests = serve((r) =>
      r.method === 'GET' && r.url.pathname.endsWith('/care-assistance')
        ? json([{ ...ready, stale: true }])
        : undefined,
    );
    render(
      <CareAssistancePanel
        profile={profile}
        actor={actor}
        mode="QUALITY"
        documentId="DOC-1"
        dirty
      />,
    );
    await screen.findByText(/资料或病历已变化/);
    fireEvent.change(screen.getByLabelText('核实或不采纳的说明'), {
      target: { value: '核实' },
    });
    expect(screen.getByRole('button', { name: '已核实并记录' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重新分析' })).toBeDisabled();
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });
  it('does not automatically call the model without a clinician', async () => {
    const requests = serve();
    render(
      <CareAssistancePanel profile={profile} actor={null} mode="PREPARE" />,
    );
    await waitFor(() =>
      expect(screen.queryByText('正在读取历史分析…')).not.toBeInTheDocument(),
    );
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });
});
