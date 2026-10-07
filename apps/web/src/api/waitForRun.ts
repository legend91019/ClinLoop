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
    signal?: AbortSignal;
  } = {},
): Promise<AgentRun | null> {
  const { attempts = 60, intervalMs = 750 } = options;
  const signal = options.signal ?? new AbortController().signal;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (signal.aborted) throw abortError();
    const runs = await loadRuns(signal);
    if (signal.aborted) throw abortError();
    const matched = runs.find(
      (run) => run.trigger_event_id === eventId && run.stop_reason,
    );
    if (matched) return matched;
    if (attempt + 1 < attempts) await pause(intervalMs, signal);
  }
  return null;
}
