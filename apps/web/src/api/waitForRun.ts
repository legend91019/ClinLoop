import type { AgentRun } from './types';

type LoadRuns = (signal: AbortSignal) => Promise<AgentRun[]>;

function abortError() {
  return new DOMException('Agent wait cancelled', 'AbortError');
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', cancelled);
      resolve();
    }, ms);
    function cancelled() {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', cancelled);
      reject(abortError());
    }
    signal.addEventListener('abort', cancelled, { once: true });
  });
}

export async function waitForAgentRun(
  eventId: string,
  loadRuns: LoadRuns,
  options: {
    attempts?: number;
    intervalMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<AgentRun | null> {
  const { attempts = 60, intervalMs = 750, timeoutMs = 45_000 } = options;
  if (options.signal?.aborted) throw abortError();
  const controller = new AbortController();
  let timeoutHandle: number | undefined;
  let cancel: (() => void) | undefined;
  const deadline = new Promise<null>((resolve) => {
    timeoutHandle = window.setTimeout(() => {
      resolve(null);
      controller.abort();
    }, timeoutMs);
  });
  const externalAbort = new Promise<never>((_, reject) => {
    cancel = () => {
      reject(abortError());
      controller.abort();
    };
    options.signal?.addEventListener('abort', cancel, { once: true });
  });
  async function poll(): Promise<AgentRun | null> {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (controller.signal.aborted) throw abortError();
      const runs = await loadRuns(controller.signal);
      if (controller.signal.aborted) throw abortError();
      const matched = runs.find(
        (run) => run.trigger_event_id === eventId && run.stop_reason,
      );
      if (matched) return matched;
      if (attempt + 1 < attempts) await pause(intervalMs, controller.signal);
    }
    return null;
  }
  try {
    return await Promise.race([poll(), deadline, externalAbort]);
  } finally {
    window.clearTimeout(timeoutHandle);
    if (cancel) options.signal?.removeEventListener('abort', cancel);
    controller.abort();
  }
}
