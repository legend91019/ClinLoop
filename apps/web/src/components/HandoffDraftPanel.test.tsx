import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '../App';
import { finding, handoff, timeline } from '../test/fixtures';
import { createDraft, identify } from '../test/interactions';
import { json, serve } from '../test/server';

describe('handoff safety and editing', () => {
  it('requires explicit encounter and identity instead of a demo encounter default', async () => {
    const requests = serve();
    render(<App />);
    expect(screen.getByRole('button', { name: '生成交接草稿' })).toBeDisabled();
    await identify();
    expect(screen.getByRole('button', { name: '生成交接草稿' })).toBeDisabled();
    expect(screen.getByLabelText('就诊 ID')).toHaveValue('');
    await userEvent.type(screen.getByLabelText('就诊 ID'), 'ENC-REAL-9');
    await userEvent.click(screen.getByRole('button', { name: '生成交接草稿' }));
    await screen.findByRole('textbox', { name: 'S · 当前情况' });
    expect(
      requests
        .find((r) => r.url.pathname.endsWith('/draft'))
        ?.url.searchParams.get('encounter_id'),
    ).toBe('ENC-REAL-9');
  });
  it('edits and saves only SBAR text; protected links are read-only', async () => {
    const requests = serve();
    render(<App />);
    const situation = await createDraft();
    await userEvent.clear(situation);
    await userEvent.type(situation, '核对后的当前情况');
    const region = screen.getByRole('region', { name: '交接草稿' });
    expect(
      within(region).getAllByRole('textbox', { name: /^[SBAR] ·/ }),
    ).toHaveLength(4);
    expect(within(region).getByText('LOOP-1')).toBeInTheDocument();
    expect(within(region).getByText('EVI-1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument();
    expect(requests.find((r) => r.method === 'PATCH')?.body).toEqual({
      situation: '核对后的当前情况',
      background: '既往背景',
      assessment: '流程评估',
      recommendation: '待跟进事项',
    });
  });
  it('blocks sealing while a high-risk finding awaits review', async () => {
    serve();
    render(<App />);
    await createDraft();
    expect(screen.getByRole('button', { name: '封存交接' })).toBeDisabled();
    expect(screen.getByText(/存在未审核事项/)).toBeInTheDocument();
  });
  it('blocks sealing when findings failed to load', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/findings')
        ? json({ detail: 'findings unavailable' }, 503)
        : undefined,
    );
    render(<App />);
    await createDraft();
    expect(screen.getByRole('button', { name: '封存交接' })).toBeDisabled();
    expect(screen.getByText(/审核状态尚未确认/)).toBeInTheDocument();
  });
  it('requires saved text then seals after rechecking findings; sealed fields cannot be edited', async () => {
    const requests = serve((r) =>
      r.url.pathname.endsWith('/findings') ? json([]) : undefined,
    );
    render(<App />);
    const situation = await createDraft();
    await userEvent.type(situation, ' · 已核对');
    expect(screen.getByRole('button', { name: '封存交接' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await screen.findByText('草稿已保存');
    await userEvent.click(screen.getByRole('button', { name: '封存交接' }));
    await userEvent.click(screen.getByRole('button', { name: '确认封存' }));
    expect(await screen.findByText('交接已封存')).toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'S · 当前情况' }),
    ).toHaveAttribute('readonly');
    expect(
      screen.queryByRole('button', { name: '保存草稿' }),
    ).not.toBeInTheDocument();
    expect(
      requests.filter((r) => r.url.pathname.endsWith('/findings')).length,
    ).toBeGreaterThanOrEqual(2);
    const seal = requests.find((r) => r.url.pathname.endsWith('/seal'))!;
    expect(seal.method).toBe('POST');
    expect(seal.headers.get('x-actor-id')).toBe('DR-EXPLICIT');
    expect(seal.body).toBeUndefined();
  });
  it('catches a newly pending finding at the final sealing check', async () => {
    let count = 0;
    const requests = serve((r) =>
      r.url.pathname.endsWith('/findings')
        ? json(++count === 1 ? [] : [finding])
        : undefined,
    );
    render(<App />);
    await createDraft();
    await userEvent.click(screen.getByRole('button', { name: '封存交接' }));
    await userEvent.click(screen.getByRole('button', { name: '确认封存' }));
    expect(await screen.findByText(/存在新的未审核事项/)).toBeInTheDocument();
    expect(requests.some((r) => r.url.pathname.endsWith('/seal'))).toBe(false);
  });
  it('preserves unsaved edits on save conflict for retry', async () => {
    let fail = true;
    serve((r) =>
      r.method === 'PATCH' && fail
        ? json({ detail: '草稿保存冲突' }, 409)
        : undefined,
    );
    render(<App />);
    const situation = await createDraft();
    await userEvent.type(situation, '本地修改');
    await userEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(await screen.findByText(/草稿保存冲突/)).toBeInTheDocument();
    expect(situation).toHaveValue('当前情况本地修改');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument();
  });
  it('loads an existing sealed report through GET and never enables text editing', async () => {
    serve((r) =>
      r.method === 'GET' && r.url.pathname.endsWith('/HAND-1')
        ? json({ ...handoff, status: 'SEALED' })
        : undefined,
    );
    render(<App />);
    await userEvent.type(screen.getByLabelText('交接报告 ID'), 'HAND-1');
    await userEvent.click(screen.getByRole('button', { name: '打开交接报告' }));
    expect(
      await screen.findByRole('textbox', { name: 'S · 当前情况' }),
    ).toHaveAttribute('readonly');
    expect(screen.getByText('已封存')).toBeInTheDocument();
  });
  it('does not render a loaded handoff from another patient', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/HAND-1')
        ? json({
            ...handoff,
            patient_id: 'P-OTHER',
            situation: 'OTHER-PATIENT-HANDOFF',
          })
        : undefined,
    );
    render(<App />);
    await userEvent.type(screen.getByLabelText('交接报告 ID'), 'HAND-1');
    await userEvent.click(screen.getByRole('button', { name: '打开交接报告' }));
    expect(
      await screen.findByText(/交接报告与当前患者不匹配/),
    ).toBeInTheDocument();
    expect(
      screen.queryByDisplayValue('OTHER-PATIENT-HANDOFF'),
    ).not.toBeInTheDocument();
  });
  it('discards a late draft when patient switches and clears encounter selection', async () => {
    let release!: (r: Response) => void;
    const late = new Promise<Response>((resolve) => {
      release = resolve;
    });
    serve((r) =>
      r.url.pathname.endsWith('/draft')
        ? late
        : r.url.pathname.includes('/P-OTHER/')
          ? r.url.pathname.endsWith('/timeline')
            ? json({ ...timeline, patient_id: 'P-OTHER', entries: [] })
            : json([])
          : undefined,
    );
    render(<App />);
    await identify();
    await userEvent.type(screen.getByLabelText('就诊 ID'), 'ENC-REAL-9');
    await userEvent.click(screen.getByRole('button', { name: '生成交接草稿' }));
    await userEvent.clear(screen.getByLabelText('患者 ID'));
    await userEvent.type(screen.getByLabelText('患者 ID'), 'P-OTHER');
    await userEvent.click(screen.getByRole('button', { name: '加载患者' }));
    await act(async () => release(json(handoff)));
    await waitFor(() =>
      expect(screen.getByLabelText('就诊 ID')).toHaveValue(''),
    );
    expect(
      screen.queryByRole('textbox', { name: 'S · 当前情况' }),
    ).not.toBeInTheDocument();
  });
});
