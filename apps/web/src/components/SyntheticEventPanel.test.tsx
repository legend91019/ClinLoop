import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { waitForAgentRun } from '../api/waitForRun';
import { json, serve } from '../test/server';
import SyntheticEventPanel from './SyntheticEventPanel';

vi.mock('../api/waitForRun', () => ({ waitForAgentRun: vi.fn() }));

describe('synthetic trial status', () => {
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
    expect(refresh).toHaveBeenCalledOnce();
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
    render(<SyntheticEventPanel patient="P-1001" onRefresh={vi.fn()} />);

    await userEvent.click(
      screen.getByRole('button', { name: '发送合成查房事件' }),
    );

    expect(
      await screen.findByText(
        /事件已接收，但无法查询 Agent 处理状态：状态服务不可用/,
      ),
    ).toBeInTheDocument();
  });
});
