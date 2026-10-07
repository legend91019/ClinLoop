import { vi } from 'vitest';
import {
  evidence,
  finding,
  handoff,
  loop,
  runs,
  source,
  timeline,
} from './fixtures';

export interface RequestRecord {
  url: URL;
  method: string;
  headers: Headers;
  body: Record<string, unknown> | undefined;
  signal?: AbortSignal | null;
}
export type Handler = (
  request: RequestRecord,
) => Response | Promise<Response> | undefined;
export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
export function serve(handler?: Handler) {
  const requests: RequestRecord[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const request: RequestRecord = {
        url: new URL(input, 'http://localhost:5173'),
        method: init?.method ?? 'GET',
        headers: new Headers(init?.headers),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        signal: init?.signal,
      };
      requests.push(request);
      const overridden = await handler?.(request);
      if (overridden) return overridden;
      const path = request.url.pathname;
      if (request.method === 'POST' && path.endsWith('/review'))
        return json({
          decision_id: 'REV-1',
          finding_id: 'FIND-1',
          action: request.body?.action,
          review_status:
            request.body?.action === 'ACCEPT' ? 'ACCEPTED' : 'REJECTED',
        });
      if (path.endsWith('/timeline'))
        return json({ ...timeline, patient_id: path.split('/')[4] });
      if (path.endsWith('/loops') && path.includes('/patients/'))
        return json([loop]);
      if (path.endsWith('/findings')) return json([finding]);
      if (path.endsWith('/trace')) return json(runs);
      if (path.endsWith('/runs')) return json(runs);
      if (path.endsWith('/source')) return json(source);
      if (path.endsWith('/EVI-1')) return json(evidence);
      if (path.endsWith('/draft')) return json(handoff);
      if (path.endsWith('/seal')) return json({ ...handoff, status: 'SEALED' });
      if (path.endsWith('/HAND-1'))
        return json({ ...handoff, ...request.body });
      if (path.endsWith('/FIND-1')) return json(finding);
      return json(
        { detail: `Unhandled request ${request.method} ${path}` },
        404,
      );
    }),
  );
  return requests;
}
