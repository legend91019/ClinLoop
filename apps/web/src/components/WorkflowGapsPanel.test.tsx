import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '../App';
import { evidence, finding, source, timeline } from '../test/fixtures';
import { identify } from '../test/interactions';
import { json, serve } from '../test/server';

describe('finding review', () => {
  it('requires explicitly entered clinician identity', async () => {
    serve();
    render(<App />);
    expect(await screen.findByText(finding.claim)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '接受' })).toBeDisabled();
    await identify();
    expect(screen.getByRole('button', { name: '接受' })).toBeEnabled();
  });
  it('accepts with entered actor headers and preserves original claim and evidence', async () => {
    const requests = serve();
    render(<App />);
    await identify();
    await userEvent.click(await screen.findByRole('button', { name: '接受' }));
    await userEvent.click(
      within(screen.getByRole('dialog', { name: '接受流程缺口' })).getByRole(
        'button',
        { name: '确认接受' },
      ),
    );
    expect(await screen.findByText(/审核已记录/)).toBeInTheDocument();
    const request = requests.find(
      (r) => r.method === 'POST' && r.url.pathname.endsWith('/review'),
    )!;
    expect(request.body).toEqual({ action: 'ACCEPT' });
    expect(request.headers.get('x-actor-id')).toBe('DR-EXPLICIT');
    expect(request.headers.get('x-actor-role')).toBe('PHYSICIAN');
    expect(screen.getByText(finding.claim)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '查看证据 EVI-1' }),
    ).toBeInTheDocument();
    expect(screen.getByText('PROGRESS_NOTES')).toBeInTheDocument();
    expect(screen.getByText('已接受')).toBeInTheDocument();
  });
  it('rejects whitespace reason locally then submits a meaningful rejection without deleting finding', async () => {
    const requests = serve();
    render(<App />);
    await identify();
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    const dialog = screen.getByRole('dialog', { name: '驳回流程缺口' });
    await userEvent.type(within(dialog).getByLabelText('审核理由'), '   ');
    await userEvent.click(
      within(dialog).getByRole('button', { name: '确认驳回' }),
    );
    expect(
      within(dialog).getByText('驳回必须填写非空理由'),
    ).toBeInTheDocument();
    expect(requests.some((r) => r.method === 'POST')).toBe(false);
    await userEvent.type(
      within(dialog).getByLabelText('审核理由'),
      '已核对原始记录',
    );
    await userEvent.click(
      within(dialog).getByRole('button', { name: '确认驳回' }),
    );
    expect(await screen.findByText('已驳回')).toBeInTheDocument();
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      action: 'REJECT',
      reason: '已核对原始记录',
    });
    expect(screen.getByText(finding.claim)).toBeInTheDocument();
  });
  it('retains review dialog and entered reason on API failure for retry', async () => {
    let fail = true;
    serve((r) =>
      r.url.pathname.endsWith('/review') && fail
        ? json({ detail: '审核暂不可用' }, 503)
        : undefined,
    );
    render(<App />);
    await identify();
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    await userEvent.type(screen.getByLabelText('审核理由'), '待核实来源');
    await userEvent.click(screen.getByRole('button', { name: '确认驳回' }));
    expect(await screen.findByText(/审核暂不可用/)).toBeInTheDocument();
    expect(screen.getByLabelText('审核理由')).toHaveValue('待核实来源');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: '确认驳回' }));
    expect(await screen.findByText('已驳回')).toBeInTheDocument();
  });
});

describe('evidence drawer', () => {
  it('wraps keyboard focus from the scrollable raw record to the drawer close button', async () => {
    serve();
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    const dialog = screen.getByRole('dialog', { name: '证据与原始记录' });
    const raw = await within(dialog).findByText(/合成原始检验记录/);
    raw.focus();
    await userEvent.keyboard('{Tab}');
    expect(
      within(dialog).getByRole('button', { name: '关闭证据' }),
    ).toHaveFocus();
    await userEvent.keyboard('{Shift>}{Tab}{/Shift}');
    expect(raw).toHaveFocus();
  });
  it('keeps the drawer outside the inert workspace and restores focus on Escape', async () => {
    serve();
    render(<App />);
    const trigger = await screen.findByRole('button', {
      name: '查看证据 EVI-1',
    });
    await userEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '证据与原始记录' });
    const shell = document.getElementById('console-shell')!;
    expect(shell).toHaveAttribute('inert');
    expect(shell.contains(dialog)).toBe(false);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(shell).not.toHaveAttribute('inert');
    expect(trigger).toHaveFocus();
  });
  it('resolves an event ID source pointer while preserving the raw payload reference', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/EVI-1')
        ? json({ ...evidence, source_id: source.event_id })
        : undefined,
    );
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    const dialog = screen.getByRole('dialog', { name: '证据与原始记录' });
    expect(
      await within(dialog).findByText(/合成原始检验记录/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('ENC-REAL-9')).toBeInTheDocument();
  });
  it('shows patient-reported trust separately and full raw source record; discovers encounter explicitly', async () => {
    serve();
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    const dialog = screen.getByRole('dialog', { name: '证据与原始记录' });
    expect(
      await within(dialog).findByText('患者自述 · 待核验'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/合成原始检验记录/)).toBeInTheDocument();
    expect(within(dialog).getByText('ENC-REAL-9')).toBeInTheDocument();
    await userEvent.click(
      within(dialog).getByRole('button', { name: '选用此就诊 ID' }),
    );
    expect(
      screen.queryByRole('dialog', { name: '证据与原始记录' }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('就诊 ID')).toHaveValue('ENC-REAL-9');
  });
  it('rejects an evidence source from another patient', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/source')
        ? json({
            ...source,
            patient_id: 'P-OTHER',
            payload: { raw_note: 'OTHER-PATIENT-PRIVATE' },
          })
        : undefined,
    );
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    expect(
      await screen.findByText(/来源记录与当前患者不匹配/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/OTHER-PATIENT-PRIVATE/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '选用此就诊 ID' }),
    ).not.toBeInTheDocument();
  });
  it('retries a missing source without claiming the record does not exist', async () => {
    let fail = true;
    serve((r) =>
      r.url.pathname.endsWith('/source') && fail
        ? json({ detail: 'source unavailable' }, 404)
        : undefined,
    );
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    const dialog = screen.getByRole('dialog', { name: '证据与原始记录' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'source unavailable',
    );
    fail = false;
    await userEvent.click(within(dialog).getByRole('button', { name: '重试' }));
    expect(
      await within(dialog).findByText(/合成原始检验记录/),
    ).toBeInTheDocument();
  });
  it('switching patients closes evidence and does not discover encounter from late old source', async () => {
    let release!: (r: Response) => void;
    const late = new Promise<Response>((resolve) => {
      release = resolve;
    });
    serve((r) =>
      r.url.pathname.endsWith('/source')
        ? late
        : r.url.pathname.includes('/P-OTHER/')
          ? r.url.pathname.endsWith('/timeline')
            ? json({ ...timeline, patient_id: 'P-OTHER', entries: [] })
            : json([])
          : undefined,
    );
    render(<App />);
    await userEvent.click(
      await screen.findByRole('button', { name: '查看证据 EVI-1' }),
    );
    await userEvent.click(screen.getByRole('button', { name: '关闭证据' }));
    await userEvent.clear(screen.getByLabelText('患者 ID'));
    await userEvent.type(screen.getByLabelText('患者 ID'), 'P-OTHER');
    await userEvent.click(screen.getByRole('button', { name: '加载患者' }));
    await act(async () => release(json(source)));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText('就诊 ID')).toHaveValue(''),
    );
  });
});
