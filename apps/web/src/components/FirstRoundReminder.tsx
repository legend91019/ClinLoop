import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { FirstRoundStatus, PatientProfile } from '../api/workspaceTypes';
import { formatTime } from './shared';

export default function FirstRoundReminder({
  profile,
  revision,
  onOpen,
}: {
  profile: PatientProfile;
  revision: number;
  onOpen: () => void;
}) {
  const [status, setStatus] = useState<FirstRoundStatus | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      void api
        .firstRound(profile.patient_id, profile.encounter_id, controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) {
            setStatus(value);
            setError('');
          }
        })
        .catch((e: Error) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    load();
    const timer = window.setInterval(load, 30000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [profile.patient_id, profile.encounter_id, revision]);
  if (!status)
    return error ? (
      <p className="panel-note">首次查房提醒暂时无法加载：{error}</p>
    ) : null;
  return (
    <aside
      className={`round-reminder ${status.state === 'OVERDUE' ? 'overdue' : ''}`}
      aria-label="首次查房提醒"
    >
      <div>
        <strong>
          {status.state === 'OVERDUE'
            ? '待办：首次查房已超过48小时'
            : status.state === 'COMPLETED'
              ? `首次查房已签署${status.completed_late ? '（逾期完成）' : ''}`
              : '首次查房：入院48小时内完成'}
        </strong>
        <p>
          {status.due_at
            ? `签署截止：${formatTime(status.due_at)}`
            : '尚无入院时间，请先补齐资料。'}
          {status.state !== 'COMPLETED' &&
            ' · 完成查房并签署记录后自动关闭提醒。'}
        </p>
      </div>
      <button className="button primary" type="button" onClick={onOpen}>
        {status.state === 'COMPLETED' ? '打开查房记录' : '去查房'}
      </button>
      {error && <p className="error-text">提醒更新失败：{error}</p>}
    </aside>
  );
}
