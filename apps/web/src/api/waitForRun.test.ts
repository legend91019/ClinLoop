import { afterEach, describe, expect, it, vi } from 'vitest';
import { runs } from '../test/fixtures';
import { waitForAgentRun } from './waitForRun';

describe('waitForAgentRun', () => {
  afterEach(() => vi.useRealTimers());

  it('ends at the elapsed deadline even when a run read never settles', async () => {
    vi.useFakeTimers();
    let requestSignal: AbortSignal | undefined;
    const listRuns = vi.fn((signal: AbortSignal) => {
      requestSignal = signal;
      return new Promise<typeof runs>(() => {});
    });
    const pending = waitForAgentRun('EVT-NEW', listRuns, { timeoutMs: 100 });

    await vi.advanceTimersByTimeAsync(100);

    await expect(pending).resolves.toBeNull();
    expect(listRuns).toHaveBeenCalledTimes(1);
    expect(requestSignal?.aborted).toBe(true);
  });

  it('cancels a stalled read immediately when the caller aborts', async () => {
    const controller = new AbortController();
    let requestSignal: AbortSignal | undefined;
    const listRuns = vi.fn((signal: AbortSignal) => {
      requestSignal = signal;
      return new Promise<typeof runs>(() => {});
    });
    const pending = waitForAgentRun('EVT-NEW', listRuns, {
      signal: controller.signal,
    });

    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(requestSignal?.aborted).toBe(true);
  });
  it('returns only the matching persisted terminal run', async () => {
    const listRuns = vi
      .fn()
      .mockResolvedValueOnce([runs[0]])
      .mockResolvedValueOnce([
        runs[0],
        { ...runs[0], run_id: 'RUN-NEW', trigger_event_id: 'EVT-NEW' },
      ]);

    const result = await waitForAgentRun('EVT-NEW', listRuns, {
      attempts: 2,
      intervalMs: 0,
    });

    expect(result?.run_id).toBe('RUN-NEW');
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it('waits for a terminal stop reason', async () => {
    const pending = {
      ...runs[0],
      trigger_event_id: 'EVT-NEW',
      stop_reason: null,
    };
    const complete = { ...pending, stop_reason: 'MODEL_ERROR' };
    const listRuns = vi
      .fn()
      .mockResolvedValueOnce([pending])
      .mockResolvedValueOnce([complete]);

    expect(
      (
        await waitForAgentRun('EVT-NEW', listRuns, {
          attempts: 2,
          intervalMs: 0,
        })
      )?.stop_reason,
    ).toBe('MODEL_ERROR');
  });

  it('returns null after a bounded number of attempts', async () => {
    const listRuns = vi.fn().mockResolvedValue([runs[0]]);

    const result = await waitForAgentRun('EVT-MISSING', listRuns, {
      attempts: 3,
      intervalMs: 0,
    });

    expect(result).toBeNull();
    expect(listRuns).toHaveBeenCalledTimes(3);
  });

  it('aborts the delay immediately', async () => {
    const controller = new AbortController();
    const listRuns = vi.fn().mockResolvedValue([]);
    const pending = waitForAgentRun('EVT-NEW', listRuns, {
      attempts: 2,
      intervalMs: 10_000,
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(listRuns).toHaveBeenCalledTimes(1));

    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});
