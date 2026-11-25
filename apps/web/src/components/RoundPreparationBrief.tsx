import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { RoundPreparation } from '../api/careTypes';
import type { PatientProfile } from '../api/workspaceTypes';
import { formatTime } from './shared';

const panels: Record<string, string> = {
  blood_culture_result: '血培养',
  blood_count_result: '血常规',
  susceptibility_result: '药敏',
  renal_function_result: '肾功能',
};
function resultText(raw: string) {
  try {
    const p = JSON.parse(raw);
    return String(p.result || p.text || raw);
  } catch {
    return raw;
  }
}

export default function RoundPreparationBrief({
  profile,
  active,
}: {
  profile: PatientProfile;
  active: boolean;
}) {
  const [data, setData] = useState<RoundPreparation | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    api
      .roundPreparation(
        profile.patient_id,
        profile.encounter_id,
        controller.signal,
      )
      .then((next) => {
        if (!controller.signal.aborted) {
          setData(next);
          setError('');
        }
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [profile.patient_id, profile.encounter_id, active, revision]);
  return (
    <section className="round-brief" aria-label="本次查房资料速览">
      <div className="workspace-section-heading">
        <div>
          <h3>查房准备单</h3>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={() => setRevision((n) => n + 1)}
        >
          刷新
        </button>
      </div>
      {error && (
        <p role="alert" className="error-text">
          准备资料加载失败：{error}
        </p>
      )}
      {!data && !error && <p>正在汇总本次就诊资料…</p>}
      {data && (
        <>
          <p>
            {data.last_round_at
              ? `对比起点：上次已提交查房 ${formatTime(data.last_round_at)}`
              : '尚无已提交查房记录，以下按首次查房准备展示。'}
          </p>
          <div className="round-brief-grid">
            <article>
              <h4>① 新回报检查 · {data.new_labs.length}</h4>
              {data.new_labs.length ? (
                data.new_labs.slice(0, 2).map((lab) => (
                  <div className="brief-item" key={lab.id}>
                    <strong>{panels[lab.label] || lab.label}</strong>
                    <small>{formatTime(lab.time)}</small>
                    <details>
                      <summary>查看报告</summary>
                      <p>{resultText(lab.text)}</p>
                      <small>{lab.id}</small>
                    </details>
                  </div>
                ))
              ) : (
                <p>暂无新增检查</p>
              )}
              {data.new_labs.length > 2 && (
                <details>
                  <summary>另有 {data.new_labs.length - 2} 份报告</summary>
                  {data.new_labs.slice(2).map((lab) => (
                    <div className="brief-item" key={lab.id}>
                      <strong>{panels[lab.label] || lab.label}</strong>
                      <small>{formatTime(lab.time)}</small>
                      <p>{resultText(lab.text)}</p>
                    </div>
                  ))}
                </details>
              )}
            </article>
            <article>
              <h4>② 未完成任务 · {data.open_tasks.length}</h4>
              {data.open_tasks.length ? (
                data.open_tasks.slice(0, 2).map((task) => (
                  <div className="brief-item" key={task.id}>
                    <strong>{task.label}</strong>
                    <p>
                      {task.due_at
                        ? `截止：${formatTime(task.due_at)}`
                        : '尚未指定截止时间'}
                    </p>
                  </div>
                ))
              ) : (
                <p>暂无已建立待办</p>
              )}
              {data.open_tasks.length > 2 && (
                <details>
                  <summary>另有 {data.open_tasks.length - 2} 项待办</summary>
                  {data.open_tasks.slice(2).map((task) => (
                    <p key={task.id}>
                      {task.label}
                      {task.due_at ? ` · ${formatTime(task.due_at)}` : ''}
                    </p>
                  ))}
                </details>
              )}
            </article>
            <article>
              <h4>③ 带到床旁核实</h4>
              <p>
                <strong>过敏史：</strong>
                {profile.allergies || '未记录，请核实'}
              </p>
              <details>
                <summary>既往史资料</summary>
                <p>{profile.history || '未记录，请核实'}</p>
              </details>
              {data.last_round ? (
                <details>
                  <summary>上次查房交代了什么</summary>
                  <p className="brief-source">{data.last_round.text}</p>
                  <small>
                    {data.last_round.label} · {formatTime(data.last_round.time)}
                  </small>
                </details>
              ) : (
                <p>首次查房请结合患者陈述补齐资料。</p>
              )}
            </article>
          </div>
          {Object.values(data.limits).some(Boolean) && (
            <p className="panel-note">
              资料较多，仅展示近期读取范围，请结合完整时间线核实。
            </p>
          )}
        </>
      )}
    </section>
  );
}
