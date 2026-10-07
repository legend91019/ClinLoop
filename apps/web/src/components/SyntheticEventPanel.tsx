import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { waitForAgentRun } from '../api/waitForRun';
import type { TimelineEntry } from '../api/types';

export default function SyntheticEventPanel({
  patient,
  timeline,
  onRefresh,
}: {
  patient: string;
  timeline?: TimelineEntry[];
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [submittedLabId, setSubmittedLabId] = useState('');
  const [submittedProgress, setSubmittedProgress] = useState(false);
  const activeWait = useRef<AbortController | null>(null);
  useEffect(() => () => activeWait.current?.abort(), []);
  if (patient !== 'P-1001') return null;
  const labEventId =
    submittedLabId ||
    [...(timeline ?? [])]
      .reverse()
      .find(
        (entry) =>
          entry.payload_ref.startsWith('LAB-DEMO-') &&
          !entry.payload_ref.startsWith('LAB-DEMO-SUS-'),
      )?.event_id ||
    '';
  const progressReady =
    submittedProgress ||
    !!timeline?.some((entry) =>
      entry.payload_ref.startsWith('NOTE-DEMO-PROGRESS-'),
    );

  async function submit(kind: 'note' | 'lab' | 'progress' | 'susceptibility') {
    setBusy(true);
    setMessage('');
    let acceptedEventId = '';
    const controller = new AbortController();
    activeWait.current = controller;
    try {
      const result =
        kind === 'note'
          ? await api.submitSyntheticNote()
          : kind === 'lab'
            ? await api.submitSyntheticLab()
            : kind === 'progress'
              ? await api.submitSyntheticProgress(labEventId)
              : await api.submitSyntheticSusceptibility();
      if (controller.signal.aborted) return;
      acceptedEventId = result.event_id;
      if (kind === 'lab') setSubmittedLabId(result.event_id);
      if (kind === 'progress') setSubmittedProgress(true);
      const labels = {
        note: '查房',
        lab: '检验',
        progress: '医生确认',
        susceptibility: '药敏',
      };
      setMessage(
        `${labels[kind]}事件已接收：${result.event_id}。正在等待 Agent 处理…`,
      );
      const run = await waitForAgentRun(
        result.event_id,
        (signal) => api.listPatientRuns(patient, signal),
        { signal: controller.signal },
      );
      onRefresh();
      if (!run) {
        setMessage(
          `${labels[kind]}事件已接收，但等待 Agent 处理超时。请检查 Worker 状态后刷新。`,
        );
      } else if (run.stop_reason === 'MODEL_ERROR') {
        const errorCode = run.trace_metadata?.error_code;
        setMessage(
          `${labels[kind]}事件已接收；Agent 处理失败${errorCode ? `（${errorCode}）` : ''}。请检查 Worker 和运行轨迹，勿直接重复发送。`,
        );
      } else {
        setMessage(
          `${labels[kind]}事件已接收；Agent 已处理，页面数据已自动刷新。`,
        );
      }
    } catch (error) {
      if (
        controller.signal.aborted ||
        (error instanceof Error && error.name === 'AbortError')
      )
        return;
      if (acceptedEventId) onRefresh();
      const detail = error instanceof Error ? error.message : '请求失败';
      setMessage(
        acceptedEventId
          ? `事件已接收，但无法查询 Agent 处理状态：${detail}`
          : detail,
      );
    } finally {
      if (activeWait.current === controller) activeWait.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section className="synthetic-event-panel" aria-label="合成事件试用">
      <div>
        <strong>试用 Agent 事件链</strong>
        <p>
          按顺序发送查房、血培养、医生确认、药敏四个合成事件。页面会等待每步
          Agent 运行完成并自动刷新任务、缺口和轨迹。仅用于 P-1001。
        </p>
      </div>
      <div className="synthetic-event-actions">
        <button
          type="button"
          className="button primary"
          aria-label="发送合成查房事件"
          disabled={busy}
          onClick={() => submit('note')}
        >
          {busy ? '发送中…' : '1. 发送合成查房事件'}
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成检验结果"
          disabled={busy}
          onClick={() => submit('lab')}
        >
          2. 发送合成检验结果
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成医生确认"
          disabled={busy || !labEventId}
          onClick={() => submit('progress')}
        >
          3. 发送合成医生确认
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成药敏结果"
          disabled={busy || !progressReady}
          onClick={() => submit('susceptibility')}
        >
          4. 发送合成药敏结果
        </button>
      </div>
      {message && (
        <p className="synthetic-event-status" role="status">
          {message}
        </p>
      )}
    </section>
  );
}
