import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App';
import { json, serve } from './test/server';
import { finding, timeline } from './test/fixtures';

describe('doctor workspace', () => {
  it('allows a 720-hour demo window and forwards it to the timeline endpoint', async () => {
    const requests = serve((r) =>
      r.url.pathname.endsWith('/timeline') &&
      r.url.searchParams.get('hours') === '24'
        ? json({ ...timeline, entries: [], count: 0 })
        : undefined,
    );
    render(<App />);
    await screen.findByText('此时间范围内暂无事件');
    await userEvent.selectOptions(screen.getByLabelText('时间范围'), '720');
    expect(await screen.findByText('检验系统')).toBeInTheDocument();
    expect(
      requests.some(
        (r) =>
          r.url.pathname.endsWith('/timeline') &&
          r.url.searchParams.get('hours') === '720',
      ),
    ).toBe(true);
  });
  it('renders all five views, synthetic disclaimer and default patient data', async () => {
    serve();
    render(<App />);
    for (const name of [
      '患者时间线',
      '未闭环任务',
      '流程缺口',
      'Agent 运行轨迹',
      '交接草稿',
    ])
      expect(screen.getByRole('heading', { name })).toBeInTheDocument();
    expect(
      screen.getByText(/工程验证，不构成临床有效性证明/),
    ).toBeInTheDocument();
    expect(await screen.findByText('检验系统')).toBeInTheDocument();
    expect(screen.getByText('追踪血培养结果与医生响应')).toBeInTheDocument();
  });
  it('reads patient from query and renders empty states independently', async () => {
    window.history.replaceState(null, '', '/?patient=P-EMPTY');
    const requests = serve((r) =>
      r.url.pathname.endsWith('/timeline')
        ? json({ ...timeline, patient_id: 'P-EMPTY', entries: [], count: 0 })
        : r.url.pathname.endsWith('/loops') ||
            r.url.pathname.endsWith('/findings')
          ? json([])
          : undefined,
    );
    render(<App />);
    expect(screen.getByLabelText('患者 ID')).toHaveValue('P-EMPTY');
    expect(await screen.findByText('此时间范围内暂无事件')).toBeInTheDocument();
    expect(screen.getByText('暂无未闭环任务')).toBeInTheDocument();
    expect(screen.getByText('暂无流程缺口')).toBeInTheDocument();
    expect(requests.some((r) => r.url.pathname.includes('/P-EMPTY/'))).toBe(
      true,
    );
  });
  it('keeps available panels usable when timeline fails and retries that resource', async () => {
    let failed = true;
    serve((r) =>
      r.url.pathname.endsWith('/timeline') && failed
        ? json({ detail: '时间线服务暂不可用' }, 503)
        : undefined,
    );
    render(<App />);
    expect(await screen.findByText(/时间线服务暂不可用/)).toBeInTheDocument();
    expect(await screen.findByText(finding.claim)).toBeInTheDocument();
    failed = false;
    await userEvent.click(
      within(screen.getByRole('region', { name: '患者时间线' })).getByRole(
        'button',
        { name: '重试' },
      ),
    );
    expect(await screen.findByText('检验系统')).toBeInTheDocument();
  });
  it('ignores late old-patient data even if transport ignores abort', async () => {
    let release!: (r: Response) => void;
    const late = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const requests = serve((r) =>
      r.url.pathname.includes('/P-1001/') &&
      r.url.pathname.endsWith('/timeline')
        ? late
        : r.url.pathname.includes('/P-2002/')
          ? r.url.pathname.endsWith('/timeline')
            ? json({
                ...timeline,
                patient_id: 'P-2002',
                entries: [
                  { ...timeline.entries[0], payload_ref: 'NEW-PATIENT-RECORD' },
                ],
              })
            : json([])
          : undefined,
    );
    render(<App />);
    await userEvent.clear(screen.getByLabelText('患者 ID'));
    await userEvent.type(screen.getByLabelText('患者 ID'), 'P-2002');
    await userEvent.click(screen.getByRole('button', { name: '加载患者' }));
    expect(await screen.findByText('NEW-PATIENT-RECORD')).toBeInTheDocument();
    await act(async () =>
      release(
        json({
          ...timeline,
          entries: [
            { ...timeline.entries[0], payload_ref: 'OLD-PATIENT-RECORD' },
          ],
        }),
      ),
    );
    expect(screen.queryByText('OLD-PATIENT-RECORD')).not.toBeInTheDocument();
    expect(
      requests.find(
        (r) =>
          r.url.pathname.includes('/P-1001/') &&
          r.url.pathname.endsWith('/timeline'),
      )?.signal?.aborted,
    ).toBe(true);
  });
  it('shows ACT arguments collapsed and expands them on demand', async () => {
    serve();
    render(<App />);
    expect(
      await screen.findByText('读取检验结果并绑定来源'),
    ).toBeInTheDocument();
    const argumentsToggle = screen.getByText('ACT 参数');
    expect(argumentsToggle.closest('details')).not.toHaveAttribute('open');
    await userEvent.click(argumentsToggle);
    expect(argumentsToggle.closest('details')).toHaveAttribute('open');
    expect(screen.getByText(/ACT-SECRET-ARG/)).toBeVisible();
    expect(screen.getByText('需要医生审核')).toBeInTheDocument();
  });
});
