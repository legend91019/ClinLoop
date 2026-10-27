import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { json, serve } from '../test/server';
import type {
  ClinicalDocument,
  Interview,
  PatientProfile,
} from '../api/workspaceTypes';
import InterviewComposer from './InterviewComposer';

const profile = { patient_id: 'P-1', encounter_id: 'ENC-1' } as PatientProfile;
const actor = { actor_id: 'DR-1', role: 'PHYSICIAN' as const };

describe('interview transcription', () => {
  it('shows a failed saved request and its retry action without expanding history', async () => {
    serve((r) => {
      if (r.url.pathname.endsWith('/clinical-writing/config'))
        return json({ configured: true, model: 'test-model' });
      if (r.url.pathname.endsWith('/interviews'))
        return json([
          {
            interview_id: 'INTV-FAILED',
            transcript: '主治医生：复查血常规。',
            kind: 'ROUND',
            saved_at: '2026-10-27T08:00:00Z',
            generation: {
              status: 'FAILED',
              error: 'NOTE_DRAFT_UNSUPPORTED_CLINICAL_PLAN',
            },
            document: null,
          },
        ]);
      return undefined;
    });
    render(
      <InterviewComposer
        profile={profile}
        actor={actor}
        active
        onReady={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    await screen.findByRole('button', { name: '重新撰写最近一次病历' });
    expect(screen.getByText('最近一次病历未生成')).toBeVisible();
    expect(
      screen.getByRole('button', { name: '重新撰写最近一次病历' }),
    ).toBeVisible();
  });
  it('defaults to real writing and can redraft a saved dialogue without replacing the source', async () => {
    const existing = {
      interview_id: 'INTV-OLD',
      transcript: '医生：复查血常规。',
      kind: 'ROUND',
      saved_at: '2026-10-27T08:00:00Z',
      generation: { status: 'READY' },
      document: { document_id: 'OLD-DRAFT', status: 'DRAFT' },
    } as Interview;
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/clinical-writing/config'))
        return json({ configured: false, model: 'test-model' });
      if (r.url.pathname.endsWith('/interviews')) return json([existing]);
      if (r.url.pathname.endsWith('/draft'))
        return json(
          { ...existing, document: null, generation: { status: 'QUEUED' } },
          202,
        );
      return undefined;
    });
    render(
      <InterviewComposer
        profile={profile}
        actor={actor}
        active
        onReady={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('撰写方式')).toHaveValue('CLINICAL');
    await screen.findByText(/尚未配置真实病历撰写模型/);
    await screen.findByText('已保存的原始对话（1）');
    await userEvent.click(screen.getByText('已保存的原始对话（1）'));
    await userEvent.click(
      screen.getByRole('button', { name: '根据原文重新撰写新版本' }),
    );
    await waitFor(() =>
      expect(requests.some((r) => r.method === 'POST')).toBe(true),
    );
    const request = requests.find((r) => r.method === 'POST');
    expect(request?.url.pathname).toContain('/P-1/interviews/INTV-OLD/draft');
    expect(request?.body).toMatchObject({ draft_mode: 'CLINICAL' });
    expect(request?.body?.request_id).toBeTruthy();
    expect(screen.getByText('医生：复查血常规。')).toBeInTheDocument();
  });
  it('keeps confirmed speech, shows interim text and stops the microphone when leaving', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/interviews') ? json([]) : undefined,
    );
    const created: SpeechMock[] = [];
    class SpeechMock {
      continuous = false;
      interimResults = false;
      lang = '';
      onresult?: (event: unknown) => void;
      onend?: () => void;
      start = vi.fn();
      stop = vi.fn(() => this.onend?.());
      abort = vi.fn();
      constructor() {
        created.push(this);
      }
    }
    vi.stubGlobal('SpeechRecognition', SpeechMock);
    const props = {
      profile,
      actor,
      active: true,
      onReady: vi.fn(),
      onDirtyChange: vi.fn(),
    };
    const view = render(<InterviewComposer {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '开始语音转录' }));
    const instance = created[0];
    expect(instance!.continuous && instance!.interimResults).toBe(true);
    act(() =>
      instance.onresult?.({
        resultIndex: 0,
        results: [
          { isFinal: true, 0: { transcript: '患者：没有发热。' } },
          { isFinal: false, 0: { transcript: '医生：计划复查' } },
        ],
      }),
    );
    expect(screen.getByLabelText('医患原始对话')).toHaveValue(
      '患者：没有发热。',
    );
    expect(screen.getByRole('status')).toHaveTextContent('医生：计划复查');
    expect(
      screen.getByRole('button', { name: '保存对话并生成病历' }),
    ).toBeDisabled();
    view.rerender(<InterviewComposer {...props} active={false} />);
    await waitFor(() => expect(instance!.stop).toHaveBeenCalled());
    expect(sessionStorage.getItem('clinloop:interview:P-1:ENC-1')).toBe(
      '患者：没有发热。',
    );
  });

  it('saves immutable dialogue with the encounter and opens a generated draft from history', async () => {
    let rows: Interview[] = [];
    const document = {
      document_id: 'DRAFT-1',
      status: 'DRAFT',
    } as ClinicalDocument;
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/interviews') && r.method === 'GET')
        return json(rows);
      if (r.url.pathname.endsWith('/interviews') && r.method === 'POST') {
        const saved = {
          interview_id: 'INTV-1',
          transcript: r.body?.transcript,
          kind: 'ROUND',
          saved_at: '2026-10-27T08:00:00Z',
          generation: { status: 'READY' },
          document,
        } as Interview;
        rows = [saved];
        return json(saved, 202);
      }
      return undefined;
    });
    const ready = vi.fn();
    render(
      <InterviewComposer
        profile={profile}
        actor={actor}
        active
        onReady={ready}
        onDirtyChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('医患原始对话'), {
      target: { value: '医生：复查血常规，结果出来后提醒我查看。' },
    });
    await userEvent.click(
      screen.getByRole('button', { name: '保存对话并生成病历' }),
    );
    await waitFor(() => expect(ready).toHaveBeenCalledWith(document));
    expect(requests.find((r) => r.method === 'POST')?.body).toMatchObject({
      encounter_id: 'ENC-1',
      kind: 'ROUND',
      transcript: '医生：复查血常规，结果出来后提醒我查看。',
    });
    expect(screen.getByLabelText('医患原始对话')).toHaveValue('');
    expect(sessionStorage.getItem('clinloop:interview:P-1:ENC-1')).toBeNull();
    await userEvent.click(screen.getByText('已保存的原始对话（1）'));
    await userEvent.click(screen.getByRole('button', { name: '打开病历草稿' }));
    expect(ready).toHaveBeenCalledTimes(2);
  });

  it('allows entering dialogue without identity and explains what is missing on save', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/interviews') ? json([]) : undefined,
    );
    render(
      <InterviewComposer
        profile={profile}
        actor={null}
        active
        onReady={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('医患原始对话'), {
      target: { value: '患者：原始问诊内容。' },
    });
    await userEvent.click(
      screen.getByRole('button', { name: '保存对话并生成病历' }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      '请先在上方填写医生 ID',
    );
    expect(screen.getByLabelText('医患原始对话')).toHaveValue(
      '患者：原始问诊内容。',
    );
  });
});
