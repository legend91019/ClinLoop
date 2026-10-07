import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App';
import { json, serve } from './test/server';
import { finding, runs, timeline } from './test/fixtures';

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
  it('shows model provider metadata and safe model errors in the trace', async () => {
    serve((r) =>
      r.url.pathname.endsWith('/runs')
        ? json([
            {
              ...runs[0],
              stop_reason: 'MODEL_ERROR',
              trace_metadata: {
                provider: 'deepseek',
                model: 'deepseek-chat',
                proposal_ref: 'PROP-1',
                error_code: 'MODEL_TIMEOUT',
              },
            },
          ])
        : undefined,
    );
    render(<App />);
    expect(await screen.findByText('模型参与')).toBeInTheDocument();
    expect(screen.getByText(/deepseek · deepseek-chat/)).toBeInTheDocument();
    expect(screen.getByText(/错误 MODEL_TIMEOUT/)).toBeInTheDocument();
    expect(screen.getByText('模型调用失败')).toBeInTheDocument();
  });
  it('shows a model failure before an Open Loop exists', async () => {
    serve((request) =>
      request.url.pathname.endsWith('/loops')
        ? json([])
        : request.url.pathname.endsWith('/runs')
          ? json([
              {
                ...runs[0],
                loop_id: null,
                run_id: 'RUN-UNBOUND',
                stop_reason: 'MODEL_ERROR',
                trace_metadata: {
                  provider: 'deepseek',
                  model: 'deepseek-chat',
                  error_code: 'MODEL_TIMEOUT',
                },
              },
            ])
          : undefined,
    );
    render(<App />);
    expect(await screen.findByText('RUN-UNBOUND')).toBeInTheDocument();
    expect(screen.getByText(/错误 MODEL_TIMEOUT/)).toBeInTheDocument();
  });
  it('submits a fixed synthetic note to start an Agent run', async () => {
    const requests = serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json(
            {
              event_id: request.body?.event_id,
              accepted: true,
              duplicate: false,
            },
            202,
          )
        : undefined,
    );
    render(<App />);
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );
    const sent = requests.find(
      (request) =>
        request.method === 'POST' && request.url.pathname.endsWith('/events'),
    );
    expect(sent?.body).toMatchObject({
      patient_id: 'P-1001',
      encounter_id: 'ENC-2001',
      event_type: 'NOTE_CREATED',
    });
    expect(await screen.findByText(/事件已接收/)).toBeInTheDocument();
  });
  it('automatically refreshes patient views after the submitted Agent run is persisted', async () => {
    let submitted = '';
    let readsAfterPost = 0;
    const requests = serve((request) => {
      if (
        request.method === 'POST' &&
        request.url.pathname.endsWith('/events')
      ) {
        submitted = String(request.body?.event_id);
        return json({ event_id: submitted, accepted: true }, 202);
      }
      if (request.url.pathname.endsWith('/runs') && submitted) {
        readsAfterPost += 1;
        return json(
          readsAfterPost === 1
            ? runs
            : [
                ...runs,
                {
                  ...runs[0],
                  run_id: 'RUN-AUTO-REFRESH',
                  trigger_event_id: submitted,
                  stop_reason: 'WAITING_EXTERNAL_EVENT',
                },
              ],
        );
      }
      return undefined;
    });
    render(<App />);
    await screen.findByText('检验系统');
    const before = requests.filter((r) =>
      r.url.pathname.endsWith('/timeline'),
    ).length;

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );

    expect(await screen.findByText(/正在等待 Agent 处理/)).toBeInTheDocument();
    expect(
      await screen.findByText(/Agent 已处理/, {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url.pathname.endsWith('/timeline')).length,
      ).toBeGreaterThan(before),
    );
    expect(await screen.findByText('RUN-AUTO-REFRESH')).toBeInTheDocument();
  });
  it('shows the stored model error after its run is persisted', async () => {
    let submitted = '';
    serve((request) => {
      if (
        request.method === 'POST' &&
        request.url.pathname.endsWith('/events')
      ) {
        submitted = String(request.body?.event_id);
        return json({ event_id: submitted, accepted: true }, 202);
      }
      if (request.url.pathname.endsWith('/runs') && submitted)
        return json([
          {
            ...runs[0],
            run_id: 'RUN-MODEL-ERROR',
            trigger_event_id: submitted,
            stop_reason: 'MODEL_ERROR',
            trace_metadata: {
              provider: 'deepseek',
              model: 'deepseek-flash',
              error_code: 'MODEL_TIMEOUT',
            },
          },
        ]);
      return undefined;
    });
    render(<App />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );

    expect(
      await screen.findByText(/Agent 处理失败.*MODEL_TIMEOUT/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    ).toBeEnabled();
  });
  it('cancels an old patient trial wait when the workspace switches patient', async () => {
    let submitted = '';
    let releaseRun!: (response: Response) => void;
    const pendingRun = new Promise<Response>((resolve) => {
      releaseRun = resolve;
    });
    const requests = serve((request) => {
      if (
        request.method === 'POST' &&
        request.url.pathname.endsWith('/events')
      ) {
        submitted = String(request.body?.event_id);
        return json({ event_id: submitted, accepted: true }, 202);
      }
      if (request.url.pathname.endsWith('/runs') && submitted)
        return pendingRun;
      if (request.url.pathname.includes('/P-2002/'))
        return request.url.pathname.endsWith('/timeline')
          ? json({ ...timeline, patient_id: 'P-2002', entries: [], count: 0 })
          : json([]);
      return undefined;
    });
    render(<App />);
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );
    await waitFor(() =>
      expect(
        requests.some(
          (r) => r.url.pathname.includes('/P-1001/runs') && r.signal,
        ),
      ).toBe(true),
    );
    await userEvent.clear(screen.getByLabelText('患者 ID'));
    await userEvent.type(screen.getByLabelText('患者 ID'), 'P-2002');
    await userEvent.click(screen.getByRole('button', { name: '加载患者' }));
    expect(await screen.findByText('此时间范围内暂无事件')).toBeInTheDocument();
    const newPatientReads = requests.filter((r) =>
      r.url.pathname.includes('/P-2002/timeline'),
    ).length;

    await act(async () =>
      releaseRun(
        json([
          { ...runs[0], trigger_event_id: submitted, run_id: 'RUN-OLD-TRIAL' },
        ]),
      ),
    );

    expect(
      requests.find((r) => r.url.pathname.includes('/P-1001/runs') && r.signal)
        ?.signal?.aborted,
    ).toBe(true);
    expect(
      requests.filter((r) => r.url.pathname.includes('/P-2002/timeline'))
        .length,
    ).toBe(newPatientReads);
    expect(screen.queryByText('RUN-OLD-TRIAL')).not.toBeInTheDocument();
  });
  it('does not start polling after a delayed event POST finishes for the previous patient', async () => {
    let releasePost!: (response: Response) => void;
    const pendingPost = new Promise<Response>((resolve) => {
      releasePost = resolve;
    });
    const requests = serve((request) => {
      if (request.method === 'POST' && request.url.pathname.endsWith('/events'))
        return pendingPost;
      if (request.url.pathname.includes('/P-2002/'))
        return request.url.pathname.endsWith('/timeline')
          ? json({ ...timeline, patient_id: 'P-2002', entries: [], count: 0 })
          : json([]);
      return undefined;
    });
    render(<App />);
    await screen.findByText('RUN-1');
    const initialRunReads = requests.filter((request) =>
      request.url.pathname.includes('/P-1001/runs'),
    ).length;
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );
    await userEvent.clear(screen.getByLabelText('患者 ID'));
    await userEvent.type(screen.getByLabelText('患者 ID'), 'P-2002');
    await userEvent.click(screen.getByRole('button', { name: '加载患者' }));
    expect(await screen.findByText('此时间范围内暂无事件')).toBeInTheDocument();

    await act(async () =>
      releasePost(json({ event_id: 'EVT-OLD-POST', accepted: true }, 202)),
    );

    expect(
      requests.filter((request) =>
        request.url.pathname.includes('/P-1001/runs'),
      ).length,
    ).toBe(initialRunReads);
  });
  it('submits a matching synthetic lab after the note so the evidence check can run', async () => {
    const requests = serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json(
            {
              event_id: request.body?.event_id,
              accepted: true,
              duplicate: false,
            },
            202,
          )
        : undefined,
    );
    render(<App />);
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    const sent = requests.find(
      (request) =>
        request.method === 'POST' && request.url.pathname.endsWith('/events'),
    );
    expect(sent?.body).toMatchObject({
      patient_id: 'P-1001',
      encounter_id: 'ENC-2001',
      event_type: 'LAB_RESULT_CREATED',
      payload: { panel: 'blood_culture_result' },
    });
    expect(await screen.findByText(/检验事件已接收/)).toBeInTheDocument();
  });
  it('links the clinician response to the lab and sends a dependent result', async () => {
    let submitted = '';
    const requests = serve((request) => {
      if (
        request.method === 'POST' &&
        request.url.pathname.endsWith('/events')
      ) {
        submitted = String(request.body?.event_id);
        return json({ event_id: submitted, accepted: true }, 202);
      }
      if (request.url.pathname.endsWith('/runs') && submitted)
        return json([
          ...runs,
          {
            ...runs[0],
            run_id: `RUN-${submitted}`,
            trigger_event_id: submitted,
          },
        ]);
      return undefined;
    });
    render(<App />);
    const acknowledge = screen.getByRole('button', {
      name: '发送合成医生确认',
    });
    expect(acknowledge).toBeDisabled();
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    const lab = requests.find(
      (request) => request.body?.event_type === 'LAB_RESULT_CREATED',
    );
    expect(lab?.body?.event_id).toBeTruthy();
    await screen.findByText(/检验事件已接收；Agent 已处理/);
    await userEvent.click(acknowledge);
    const progress = requests.find(
      (request) => request.body?.event_type === 'PROGRESS_NOTE_CREATED',
    );
    expect(progress?.body).toMatchObject({
      payload: {
        acknowledges_event_id: lab?.body?.event_id,
        creates_dependency: 'susceptibility_result',
      },
    });
    await screen.findByText(/医生确认事件已接收；Agent 已处理/);
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成药敏结果' }),
    );
    const susceptibility = requests.find(
      (request) =>
        request.body?.payload &&
        (request.body.payload as Record<string, unknown>).panel ===
          'susceptibility_result',
    );
    expect(susceptibility?.body).toMatchObject({
      event_type: 'LAB_RESULT_CREATED',
      payload: { panel: 'susceptibility_result' },
    });
  });
});
