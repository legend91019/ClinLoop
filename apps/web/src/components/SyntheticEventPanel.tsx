import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import { waitForAgentRun } from '../api/waitForRun';

type EventKind = 'note' | 'lab' | 'progress' | 'susceptibility';
type PendingCheck = {
  kind: EventKind;
  eventId: string;
  suffix: string;
  sendOutcome: 'unknown' | 'accepted';
};
type TrialState = {
  confirmedLabId: string;
  confirmedProgress: boolean;
  pendingCheck: PendingCheck | null;
};
const trialStorageKey = 'clinloop:synthetic-trial:P-1001';
const emptyTrial: TrialState = {
  confirmedLabId: '',
  confirmedProgress: false,
  pendingCheck: null,
};
const eventPrefixes: Record<EventKind, string> = {
  note: 'EVT-DEMO-',
  lab: 'EVT-DEMO-LAB-',
  progress: 'EVT-DEMO-PROGRESS-',
  susceptibility: 'EVT-DEMO-SUS-',
};
function readTrial(): TrialState {
  try {
    const raw = window.sessionStorage.getItem(trialStorageKey);
    if (!raw) return emptyTrial;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return emptyTrial;
    const stored = value as Partial<TrialState>;
    const pending = stored.pendingCheck;
    return {
      confirmedLabId:
        typeof stored.confirmedLabId === 'string' &&
        stored.confirmedLabId.startsWith(eventPrefixes.lab)
          ? stored.confirmedLabId
          : '',
      confirmedProgress: stored.confirmedProgress === true,
      pendingCheck:
        pending &&
        pending.kind in eventPrefixes &&
        typeof pending.suffix === 'string' &&
        pending.eventId === eventPrefixes[pending.kind] + pending.suffix &&
        ['unknown', 'accepted'].includes(pending.sendOutcome)
          ? pending
          : null,
    };
  } catch {
    return emptyTrial;
  }
}
const labels: Record<EventKind, string> = {
  note: '查房',
  lab: '检验',
  progress: '医生确认',
  susceptibility: '药敏',
};

export default function SyntheticEventPanel({
  patient,
  onRefresh,
}: {
  patient: string;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const saved = useRef(readTrial());
  const [confirmedLabId, setConfirmedLabId] = useState(
    saved.current.confirmedLabId,
  );
  const [confirmedProgress, setConfirmedProgress] = useState(
    saved.current.confirmedProgress,
  );
  const [pendingCheck, setPendingCheck] = useState<PendingCheck | null>(
    saved.current.pendingCheck,
  );
  const activeWait = useRef<AbortController | null>(null);
  useEffect(() => () => activeWait.current?.abort(), []);
  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        trialStorageKey,
        JSON.stringify({ confirmedLabId, confirmedProgress, pendingCheck }),
      );
    } catch {
      // Keep the current trial usable even when browser storage is unavailable.
    }
  }, [confirmedLabId, confirmedProgress, pendingCheck]);
  if (patient !== 'P-1001') return null;
  const labEventId = confirmedLabId;
  const progressReady = confirmedProgress;

  async function confirmAcceptedEvent(
    kind: EventKind,
    eventId: string,
    controller: AbortController,
    acceptedKnown = true,
  ) {
    setPendingCheck({
      kind,
      eventId,
      suffix: eventId.slice(eventPrefixes[kind].length),
      sendOutcome: acceptedKnown ? 'accepted' : 'unknown',
    });
    setMessage(
      acceptedKnown
        ? `${labels[kind]}事件已接收：${eventId}。正在等待 Agent 处理…`
        : `正在查询事件 ${eventId} 的 Agent 状态…`,
    );
    try {
      const run = await waitForAgentRun(
        eventId,
        (signal) => api.listPatientRuns(patient, signal),
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      if (!run) {
        setMessage(
          acceptedKnown
            ? `${labels[kind]}事件已接收，但等待 Agent 处理超时。请检查 Worker 后重新查询 Agent 状态。`
            : `事件 ${eventId} 的接收与处理状态仍未确认。请检查 API 后重试发送同一事件 ID。`,
        );
        return;
      }
      setPendingCheck(null);
      onRefresh();
      if (run.stop_reason === 'MODEL_ERROR') {
        const errorCode = run.trace_metadata?.error_code;
        setMessage(
          `${labels[kind]}事件已接收；Agent 处理失败${errorCode ? `（${errorCode}）` : ''}。请检查 Worker 和运行轨迹，勿直接重复发送。`,
        );
      } else {
        const progressed = [
          'WAITING_EXTERNAL_EVENT',
          'REQUIRES_CLINICIAN_REVIEW',
          'SUFFICIENT_EVIDENCE',
        ].includes(run.stop_reason ?? '');
        if (progressed && kind === 'lab') setConfirmedLabId(eventId);
        if (progressed && kind === 'progress') setConfirmedProgress(true);
        setMessage(
          progressed
            ? `${labels[kind]}事件已接收；Agent 已处理，页面数据已自动刷新。`
            : `${labels[kind]}事件已接收；Agent 已停止（${run.stop_reason}），请检查运行轨迹后继续。`,
        );
      }
    } catch (error) {
      if (
        controller.signal.aborted ||
        (error instanceof Error && error.name === 'AbortError')
      )
        return;
      const detail = error instanceof Error ? error.message : '请求失败';
      setMessage(
        acceptedKnown
          ? `事件已接收，但无法查询 Agent 处理状态：${detail}。请重新查询 Agent 状态。`
          : `事件 ${eventId} 状态查询失败：${detail}。请检查 API 后重试。`,
      );
    }
  }

  async function submit(kind: EventKind) {
    setBusy(true);
    setMessage('');
    if (kind === 'lab') {
      setConfirmedLabId('');
      setConfirmedProgress(false);
    }
    if (kind === 'progress') setConfirmedProgress(false);
    const controller = new AbortController();
    activeWait.current = controller;
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const eventId = `${eventPrefixes[kind]}${suffix}`;
    setPendingCheck({ kind, eventId, suffix, sendOutcome: 'unknown' });
    try {
      const result = await sendEvent(kind, suffix);
      if (controller.signal.aborted) return;
      if (!result.accepted || result.event_id !== eventId)
        throw new Error('事件接收结果不一致，请查询 Agent 状态');
      await confirmAcceptedEvent(kind, eventId, controller);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 409) {
        await confirmAcceptedEvent(kind, eventId, controller);
      } else if (
        error instanceof ApiError &&
        [400, 401, 403, 404, 422].includes(error.status)
      ) {
        setPendingCheck(null);
        setMessage(error.message);
      } else {
        setMessage(
          `事件 ${eventId} 发送结果未知。请先查询 Agent 状态，或重试发送同一事件 ID。`,
        );
      }
    } finally {
      if (activeWait.current === controller) activeWait.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function retryCheck() {
    if (!pendingCheck) return;
    setBusy(true);
    const controller = new AbortController();
    activeWait.current = controller;
    try {
      await confirmAcceptedEvent(
        pendingCheck.kind,
        pendingCheck.eventId,
        controller,
        pendingCheck.sendOutcome === 'accepted',
      );
    } finally {
      if (activeWait.current === controller) activeWait.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function sendEvent(kind: EventKind, suffix: string) {
    return kind === 'note'
      ? api.submitSyntheticNote(suffix)
      : kind === 'lab'
        ? api.submitSyntheticLab(suffix)
        : kind === 'progress'
          ? api.submitSyntheticProgress(labEventId, suffix)
          : api.submitSyntheticSusceptibility(suffix);
  }

  async function retrySend() {
    if (!pendingCheck) return;
    setBusy(true);
    const controller = new AbortController();
    activeWait.current = controller;
    try {
      const result = await sendEvent(pendingCheck.kind, pendingCheck.suffix);
      if (controller.signal.aborted) return;
      if (!result.accepted || result.event_id !== pendingCheck.eventId)
        throw new Error('事件接收结果不一致，请查询 Agent 状态');
      await confirmAcceptedEvent(
        pendingCheck.kind,
        pendingCheck.eventId,
        controller,
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 409) {
        await confirmAcceptedEvent(
          pendingCheck.kind,
          pendingCheck.eventId,
          controller,
        );
      } else {
        setMessage(
          `事件 ${pendingCheck.eventId} 发送结果未知。请检查 API 后重试同一事件 ID。`,
        );
      }
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
          disabled={busy || !!pendingCheck}
          onClick={() => submit('note')}
        >
          {busy ? '发送中…' : '1. 发送合成查房事件'}
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成检验结果"
          disabled={busy || !!pendingCheck}
          onClick={() => submit('lab')}
        >
          2. 发送合成检验结果
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成医生确认"
          disabled={busy || !!pendingCheck || !labEventId}
          onClick={() => submit('progress')}
        >
          3. 发送合成医生确认
        </button>
        <button
          type="button"
          className="button"
          aria-label="发送合成药敏结果"
          disabled={busy || !!pendingCheck || !progressReady}
          onClick={() => submit('susceptibility')}
        >
          4. 发送合成药敏结果
        </button>
        {pendingCheck && (
          <>
            <button
              type="button"
              className="button"
              aria-label="重新查询 Agent 状态"
              disabled={busy}
              onClick={retryCheck}
            >
              重新查询 Agent 状态
            </button>
            <button
              type="button"
              className="button"
              aria-label="重试发送同一事件"
              disabled={busy}
              onClick={retrySend}
            >
              重试发送同一事件
            </button>
          </>
        )}
      </div>
      {message && (
        <p className="synthetic-event-status" role="status">
          {message}
        </p>
      )}
    </section>
  );
}
