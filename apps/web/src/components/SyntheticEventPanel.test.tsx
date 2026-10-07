import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { waitForAgentRun } from '../api/waitForRun';
import { runs } from '../test/fixtures';
import { json, serve } from '../test/server';
import SyntheticEventPanel from './SyntheticEventPanel';

vi.mock('../api/waitForRun', () => ({ waitForAgentRun: vi.fn() }));

describe('synthetic trial status', () => {
  it('remains usable when session storage rejects writes', () => {
    const write = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new DOMException('Storage unavailable', 'QuotaExceededError');
      });
    try {
      render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);
      expect(screen.getByRole('button', { name: '发送合成查房事件' })).toBeEnabled();
    } finally {
      write.mockRestore();
    }
  });

  it('shows a Worker timeout without claiming Agent success', async () => {
    vi.mocked(waitForAgentRun).mockResolvedValueOnce(null);
    const refresh = vi.fn();
    serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    render(<SyntheticEventPanel patient="P-1001" onRefresh={refresh} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );

    expect(await screen.findByText(/等待 Agent 处理超时/)).toBeInTheDocument();
    expect(screen.queryByText(/Agent 已处理/)).not.toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it('keeps an accepted event distinct from a failed status query', async () => {
    vi.mocked(waitForAgentRun).mockRejectedValueOnce(
      new Error('状态服务不可用'),
    );
    serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    const refresh = vi.fn();
    render(<SyntheticEventPanel patient="P-1001" onRefresh={refresh} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );

    expect(
      await screen.findByText(
        /事件已接收，但无法查询 Agent 处理状态：状态服务不可用/,
      ),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it('keeps doctor acknowledgement locked when the lab run is unconfirmed', async () => {
    vi.mocked(waitForAgentRun).mockResolvedValueOnce(null);
    serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );

    expect(await screen.findByText(/等待 Agent 处理超时/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '发送合成医生确认' }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: '重新查询 Agent 状态' }),
    ).toBeEnabled();
  });

  it('rechecks the accepted lab without sending another event', async () => {
    vi.mocked(waitForAgentRun)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        ...runs[0],
        stop_reason: 'REQUIRES_CLINICIAN_REVIEW',
      });
    const requests = serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    expect(await screen.findByText(/等待 Agent 处理超时/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: '重新查询 Agent 状态' }),
    );

    expect(
      await screen.findByText(/检验事件已接收；Agent 已处理/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '发送合成医生确认' }),
    ).toBeEnabled();
    expect(
      requests.filter((request) => request.method === 'POST'),
    ).toHaveLength(1);
  });

  it('keeps susceptibility locked when the progress run cannot be read', async () => {
    vi.mocked(waitForAgentRun)
      .mockResolvedValueOnce({
        ...runs[0],
        stop_reason: 'REQUIRES_CLINICIAN_REVIEW',
      })
      .mockRejectedValueOnce(new Error('状态服务不可用'));
    serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    expect(
      await screen.findByText(/检验事件已接收；Agent 已处理/),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成医生确认' }),
    );

    expect(
      await screen.findByText(/无法查询 Agent 处理状态/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '发送合成药敏结果' }),
    ).toBeDisabled();
  });

  it('restores the accepted event after remount and rechecks without another POST', async () => {
    vi.mocked(waitForAgentRun)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        ...runs[0],
        stop_reason: 'REQUIRES_CLINICIAN_REVIEW',
      });
    const requests = serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    const first = render(
      <SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    expect(await screen.findByText(/等待 Agent 处理超时/)).toBeInTheDocument();
    first.unmount();
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '重新查询 Agent 状态' }),
    );

    expect(
      await screen.findByText(/检验事件已接收；Agent 已处理/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '发送合成医生确认' }),
    ).toBeEnabled();
    expect(
      requests.filter((request) => request.method === 'POST'),
    ).toHaveLength(1);
  });

  it('restores a confirmed lab after remount so the doctor step remains available', async () => {
    vi.mocked(waitForAgentRun).mockResolvedValueOnce({ ...runs[0] });
    const requests = serve((request) =>
      request.method === 'POST' && request.url.pathname.endsWith('/events')
        ? json({ event_id: request.body?.event_id, accepted: true }, 202)
        : undefined,
    );
    const first = render(
      <SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    expect(
      await screen.findByText(/检验事件已接收；Agent 已处理/),
    ).toBeInTheDocument();
    first.unmount();
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    expect(
      screen.getByRole('button', { name: '发送合成医生确认' }),
    ).toBeEnabled();
    expect(
      requests.filter((request) => request.method === 'POST'),
    ).toHaveLength(1);
  });

  it('resends an ambiguous POST with the same event ID', async () => {
    let posts = 0;
    const requests = serve((request) => {
      if (
        request.method !== 'POST' ||
        !request.url.pathname.endsWith('/events')
      )
        return undefined;
      posts += 1;
      if (posts === 1) throw new TypeError('response lost');
      return json({ detail: 'already ingested' }, 409);
    });
    vi.mocked(waitForAgentRun).mockResolvedValueOnce({ ...runs[0] });
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成检验结果' }),
    );
    expect(await screen.findByText(/发送结果未知/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: '重试发送同一事件' }),
    );

    expect(
      await screen.findByText(/检验事件已接收；Agent 已处理/),
    ).toBeInTheDocument();
    const sent = requests.filter((request) => request.method === 'POST');
    expect(sent).toHaveLength(2);
    expect(sent[0].body?.event_id).toBe(sent[1].body?.event_id);
    expect(sent[0].body?.payload_ref).toBe(sent[1].body?.payload_ref);
  });
});
