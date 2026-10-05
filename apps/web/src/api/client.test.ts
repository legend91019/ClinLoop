import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from './client';
import { serve, json } from '../test/server';
import { finding, handoff } from '../test/fixtures';

const actor = { actor_id: 'DR-EXPLICIT', role: 'PHYSICIAN' as const };
describe('ApiClient HTTP contracts', () => {
  it('defaults to localhost:8000 and uses encoded patient IDs with 24-hour timeline', async () => {
    const requests = serve();
    const client = new ApiClient();
    await client.listTimeline('P/a b');
    expect(requests[0].url.origin).toBe('http://localhost:8000');
    expect(requests[0].url.pathname).toBe(
      '/api/v1/patients/P%2Fa%20b/timeline',
    );
    expect(requests[0].url.searchParams.get('hours')).toBe('24');
  });
  it('supports relative /api without duplicating the API prefix', async () => {
    const requests = serve();
    await new ApiClient('/api').listLoops('P-1001');
    expect(requests[0].url.pathname).toBe('/api/v1/patients/P-1001/loops');
  });
  it('throws ApiError for a structured non-2xx response', async () => {
    serve(() => json({ detail: '审核冲突' }, 409));
    await expect(new ApiClient().getFinding('FIND-1')).rejects.toMatchObject({
      status: 409,
      message: '审核冲突',
    });
  });
  it('handles non-JSON errors and network failures without losing retry information', async () => {
    serve(() => new Response('gateway unavailable', { status: 502 }));
    await expect(new ApiClient().listLoops('P-1001')).rejects.toBeInstanceOf(
      ApiError,
    );
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    );
    await expect(new ApiClient().listLoops('P-1001')).rejects.toMatchObject({
      status: 0,
    });
  });
  it('sends an explicit clinician and no patient state in review payload', async () => {
    const requests = serve();
    const result = await new ApiClient().reviewFinding(
      'FIND-1',
      'REJECT',
      '  已核实  ',
      actor,
    );
    expect(result.review_status).toBe('REJECTED');
    expect(requests[0].body).toEqual({ action: 'REJECT', reason: '已核实' });
    expect(requests[0].headers.get('x-actor-id')).toBe('DR-EXPLICIT');
    expect(requests[0].headers.get('x-actor-role')).toBe('PHYSICIAN');
  });
  it('requires identity, rejection reason and encounter before write requests', async () => {
    const requests = serve();
    const client = new ApiClient();
    await expect(
      client.reviewFinding('FIND-1', 'ACCEPT', '', { ...actor, actor_id: ' ' }),
    ).rejects.toThrow();
    await expect(
      client.reviewFinding('FIND-1', 'REJECT', ' ', actor),
    ).rejects.toThrow();
    await expect(
      client.createHandoffDraft('P-OTHER', '', actor),
    ).rejects.toThrow();
    expect(requests).toHaveLength(0);
  });
  it('sends only four draft text fields even when given a response containing protected IDs', async () => {
    const requests = serve();
    const supplied = { ...handoff, status: 'SEALED', evidence_ids: ['forged'] };
    await new ApiClient().updateHandoff('HAND-1', supplied, actor);
    expect(requests[0].method).toBe('PATCH');
    expect(requests[0].body).toEqual({
      situation: '当前情况',
      background: '既往背景',
      assessment: '流程评估',
      recommendation: '待跟进事项',
    });
  });
  it('reads patient findings, evidence/source, handoff and passes cancellation signal', async () => {
    const requests = serve();
    const client = new ApiClient();
    const controller = new AbortController();
    expect(await client.listFindings('P-1001', controller.signal)).toEqual([
      finding,
    ]);
    expect((await client.getEvidenceSource('EVI-1')).encounter_id).toBe(
      'ENC-REAL-9',
    );
    expect((await client.getHandoff('HAND-1')).handoff_id).toBe('HAND-1');
    expect(requests[0].signal).toBe(controller.signal);
  });
});
