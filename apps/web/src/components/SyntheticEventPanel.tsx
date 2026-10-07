import { useState } from 'react';
import { api } from '../api/client';
import type { TimelineEntry } from '../api/types';

export default function SyntheticEventPanel({
  patient,
  timeline,
}: {
  patient: string;
  timeline?: TimelineEntry[];
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [submittedLabId, setSubmittedLabId] = useState('');
  const [submittedProgress, setSubmittedProgress] = useState(false);
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
    try {
      const result =
        kind === 'note'
          ? await api.submitSyntheticNote()
          : kind === 'lab'
            ? await api.submitSyntheticLab()
            : kind === 'progress'
              ? await api.submitSyntheticProgress(labEventId)
              : await api.submitSyntheticSusceptibility();
      if (kind === 'lab') setSubmittedLabId(result.event_id);
      if (kind === 'progress') setSubmittedProgress(true);
      const labels = {
        note: '查房',
        lab: '检验',
        progress: '医生确认',
        susceptibility: '药敏',
      };
      setMessage(
        `${labels[kind]}事件已接收：${result.event_id}。请等 Worker 处理后点击上方刷新按钮，查看 Agent 运行轨迹。`,
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : '事件发送失败，请重试',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="synthetic-event-panel" aria-label="合成事件试用">
      <div>
        <strong>试用 Agent 事件链</strong>
        <p>
          按顺序发送查房、血培养、医生确认、药敏四个合成事件。每步等待 Worker
          处理后点击上方刷新按钮；在任务、缺口和运行轨迹中核对变化。仅用于
          P-1001。
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
