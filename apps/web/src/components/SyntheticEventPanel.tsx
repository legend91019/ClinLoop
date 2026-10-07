import { useState } from 'react';
import { api } from '../api/client';

export default function SyntheticEventPanel({ patient }: { patient: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  if (patient !== 'P-1001') return null;

  async function submit(kind: 'note' | 'lab') {
    setBusy(true);
    setMessage('');
    try {
      const result =
        kind === 'note'
          ? await api.submitSyntheticNote()
          : await api.submitSyntheticLab();
      setMessage(
        `${kind === 'note' ? '查房' : '检验'}事件已接收：${result.event_id}。请等 Worker 处理后刷新页面，查看 Agent 运行轨迹。`,
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
          先发送合成查房记录，等运行轨迹出现新的跟进任务；再发送合成检验结果，刷新查看工具核对与待审核告警。仅用于
          P-1001。
        </p>
      </div>
      <div className="synthetic-event-actions">
        <button
          type="button"
          className="button primary"
          disabled={busy}
          onClick={() => submit('note')}
        >
          {busy ? '发送中…' : '发送合成查房事件'}
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => submit('lab')}
        >
          发送合成检验结果
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
