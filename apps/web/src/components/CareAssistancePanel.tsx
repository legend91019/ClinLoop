import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { Clinician } from '../api/types';
import type {
  CareDecision,
  CareMode,
  CareRun,
  CareTask,
} from '../api/careTypes';
import type { ClinicalDocument, PatientProfile } from '../api/workspaceTypes';
import { formatTime } from './shared';

const titles = {
  PREPARE: '查房前准备',
  QUALITY: '病历质量核查',
  PLAN: '条件任务计划',
};
const descriptions = {
  PREPARE: '汇总上次查房后的变化、未完成事项和本次需要核实的问题。',
  QUALITY: '对照原始对话、检查与已有病历，检查遗漏、矛盾及缺少依据的描述。',
  PLAN: '从已签署病历理解任务顺序和等待条件；确认后持续跟进，可记录原因调整计划。',
};
const statuses = {
  QUEUED: '等待后台处理',
  RUNNING: '正在查询资料并分析',
  READY: '分析完成，待医生核对',
  FAILED: '分析失败',
  ACTIVE: '计划跟进中',
};
const tools: Record<string, string> = {
  read_documents: '查阅病历和原始对话',
  read_labs: '查询检验结果',
  read_tasks: '核对已有任务',
};
const categories: Record<string, string> = {
  CHANGE: '新增变化',
  GAP: '资料缺口',
  CONFLICT: '信息冲突',
  OMISSION: '可能遗漏',
  UNSUPPORTED: '依据不足',
  QUESTION: '待核实',
};

function PlanEditor({
  run,
  busy,
  onDecide,
}: {
  run: CareRun;
  busy: boolean;
  onDecide: (decision: Omit<CareDecision, 'revision'>) => Promise<void>;
}) {
  const [tasks, setTasks] = useState<CareTask[]>(run.result?.tasks || []);
  const [reason, setReason] = useState('');
  const [editing, setEditing] = useState(false);
  function edit(index: number, patch: Partial<CareTask>) {
    setTasks((rows) =>
      rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  }
  return (
    <div className="care-plan">
      {tasks.map((task, i) => {
        const state = run.task_states?.[task.key];
        const finished =
          state && ['RESOLVED', 'CANCELLED'].includes(state.state);
        return (
          <article className="care-item" key={task.key}>
            <strong>
              {i + 1}. {task.goal}
            </strong>
            <p className="panel-note">病历原文：{task.source_quote}</p>
            <p>
              {state?.message ||
                (task.condition === 'RESULT'
                  ? '等待检查结果'
                  : task.condition === 'CLARIFY'
                    ? task.question
                    : '医生确认后可跟进')}
              {state?.overdue && (
                <b className="error-text"> · 已超过截止时间</b>
              )}
            </p>
            <small>
              前置任务：
              {task.depends_on
                .map((key) => tasks.find((t) => t.key === key)?.goal || key)
                .join('；') || '无'}{' '}
              · 截止：{task.due_at ? formatTime(task.due_at) : '未指定'}
            </small>
            {task.existing_loop_id && (
              <p role="status">
                已有相似任务，请先到医生待办核对，避免重复安排。
              </p>
            )}
            {state?.result_ids.length ? (
              <p>
                匹配结果：{state.result_ids.join('、')}
                （请在患者时间线核对原始结果）
              </p>
            ) : null}
            {editing && !finished && (
              <div className="care-edit-grid">
                <label>
                  任务内容
                  <input
                    value={task.goal}
                    onChange={(e) => edit(i, { goal: e.target.value })}
                  />
                </label>
                <label>
                  执行条件
                  <select
                    value={task.condition}
                    onChange={(e) =>
                      edit(i, {
                        condition: e.target.value as CareTask['condition'],
                      })
                    }
                  >
                    <option value="NONE">无额外条件／医生已核实</option>
                    <option value="RESULT">等待检查结果</option>
                    <option value="CLARIFY">需要澄清</option>
                  </select>
                </label>
                {task.condition === 'RESULT' && (
                  <label>
                    等待项目
                    <select
                      value={task.panel}
                      onChange={(e) => edit(i, { panel: e.target.value })}
                    >
                      <option value="">请选择</option>
                      <option value="blood_culture_result">血培养</option>
                      <option value="susceptibility_result">药敏</option>
                      <option value="blood_count_result">血常规</option>
                      <option value="renal_function_result">肾功能</option>
                    </select>
                  </label>
                )}
                {task.condition === 'CLARIFY' && (
                  <label>
                    待澄清问题
                    <input
                      value={task.question}
                      onChange={(e) => edit(i, { question: e.target.value })}
                    />
                  </label>
                )}
                <label>
                  前置任务（可多选）
                  <select
                    multiple
                    value={task.depends_on}
                    onChange={(e) =>
                      edit(i, {
                        depends_on: Array.from(
                          e.target.selectedOptions,
                          (o) => o.value,
                        ),
                      })
                    }
                  >
                    {tasks
                      .filter((other) => other.key !== task.key)
                      .map((other) => (
                        <option key={other.key} value={other.key}>
                          {other.goal}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  截止时间
                  <input
                    type="datetime-local"
                    value={
                      task.due_at
                        ? new Date(
                            new Date(task.due_at).getTime() -
                              new Date(task.due_at).getTimezoneOffset() * 60000,
                          )
                            .toISOString()
                            .slice(0, 16)
                        : ''
                    }
                    onChange={(e) =>
                      edit(i, {
                        due_at: e.target.value
                          ? new Date(e.target.value).toISOString()
                          : null,
                      })
                    }
                  />
                </label>
              </div>
            )}
            {run.status === 'ACTIVE' && !finished && (
              <div className="workspace-actions">
                <button
                  type="button"
                  className="button"
                  disabled={busy || !reason.trim() || state?.state !== 'READY'}
                  onClick={() =>
                    void onDecide({
                      action: 'RESOLVE',
                      item_key: task.key,
                      reason,
                    })
                  }
                >
                  确认处理完成
                </button>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy || !reason.trim()}
                  onClick={() =>
                    void onDecide({
                      action: 'DISMISS',
                      item_key: task.key,
                      reason,
                    })
                  }
                >
                  取消此任务
                </button>
              </div>
            )}
          </article>
        );
      })}
      {!!tasks.length && (
        <>
          <label>
            确认、处理或调整说明
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="记录核对依据、处理意见或计划变更原因"
            />
          </label>
          <div className="workspace-actions">
            <button
              type="button"
              className="button"
              onClick={() => setEditing(!editing)}
            >
              {editing ? '收起调整' : '调整任务条件与时间'}
            </button>
            <button
              type="button"
              className="button primary"
              disabled={
                busy || !reason.trim() || (run.status === 'READY' && run.stale)
              }
              onClick={() =>
                void onDecide({
                  action: run.status === 'ACTIVE' ? 'UPDATE' : 'ACCEPT',
                  reason,
                  tasks,
                })
              }
            >
              {run.status === 'ACTIVE' ? '保存计划调整' : '确认计划并创建待办'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function CareAssistancePanel({
  profile,
  actor,
  mode,
  documentId,
  active = true,
  dirty = false,
}: {
  profile: PatientProfile;
  actor: Clinician | null;
  mode: CareMode;
  documentId?: string;
  active?: boolean;
  dirty?: boolean;
}) {
  const [runs, setRuns] = useState<CareRun[]>([]);
  const [docs, setDocs] = useState<ClinicalDocument[]>([]);
  const [selected, setSelected] = useState('');
  const [selectedRun, setSelectedRun] = useState('');
  const [clarification, setClarification] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const automatic = useRef(new Set<string>());
  const target = documentId || selected;
  const filtered = runs.filter(
    (r) => r.mode === mode && (mode === 'PREPARE' || r.document_id === target),
  );
  const run = filtered.find((r) => r.run_id === selectedRun) || filtered[0];
  const waiting = run?.status === 'QUEUED' || run?.status === 'RUNNING';
  useEffect(() => {
    if (!active || !loaded || !actor || dirty || mode === 'PLAN' || run || busy)
      return;
    if (mode === 'QUALITY' && !target) return;
    const key = `${profile.patient_id}:${profile.encounter_id}:${mode}:${target}`;
    if (automatic.current.has(key)) return;
    automatic.current.add(key);
    let cancelled = false;
    api
      .requestCare(
        profile.patient_id,
        {
          encounter_id: profile.encounter_id,
          mode,
          ...(target ? { document_id: target } : {}),
          clarification: '',
        },
        actor,
      )
      .then((next) => {
        if (!cancelled)
          setRuns((rows) => [
            next,
            ...rows.filter((r) => r.run_id !== next.run_id),
          ]);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [
    active,
    loaded,
    actor,
    dirty,
    mode,
    run,
    busy,
    target,
    profile.patient_id,
    profile.encounter_id,
  ]);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const rows = await api.careRuns(
          profile.patient_id,
          profile.encounter_id,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setRuns(rows);
          setLoaded(true);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [profile.patient_id, profile.encounter_id, active]);
  useEffect(() => {
    if (mode !== 'PLAN' || !active || documentId) return;
    const controller = new AbortController();
    api
      .listDocuments(
        profile.patient_id,
        profile.encounter_id,
        controller.signal,
      )
      .then((rows) => {
        if (!controller.signal.aborted)
          setDocs(rows.filter((d) => d.status === 'SUBMITTED'));
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [profile.patient_id, profile.encounter_id, mode, active, documentId]);
  async function generate() {
    if (!actor) {
      setError('请先填写医生 ID 并选择临床角色');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const next = await api.requestCare(
        profile.patient_id,
        {
          encounter_id: profile.encounter_id,
          mode,
          ...(target ? { document_id: target } : {}),
          clarification,
        },
        actor,
      );
      setRuns((rows) => [
        next,
        ...rows.filter((r) => r.run_id !== next.run_id),
      ]);
      setSelectedRun(next.run_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide(body: Omit<CareDecision, 'revision'>) {
    if (!actor || !run) return;
    setBusy(true);
    setError('');
    try {
      const next = await api.decideCare(
        profile.patient_id,
        run.run_id,
        { ...body, revision: run.revision },
        actor,
      );
      setRuns((rows) => rows.map((r) => (r.run_id === next.run_id ? next : r)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="care-assistance" aria-label={titles[mode]}>
      <div className="workspace-section-heading">
        <div>
          <p className="eyebrow">PATIENT AGENT</p>
          <h3>{titles[mode]}</h3>
          <p>{descriptions[mode]}</p>
        </div>
        <button
          type="button"
          className="button primary"
          disabled={busy || waiting || dirty || (mode !== 'PREPARE' && !target)}
          onClick={() => void generate()}
        >
          {waiting ? statuses[run.status] : run ? '重新分析' : '开始分析'}
        </button>
      </div>
      {mode === 'PLAN' && !documentId && (
        <label>
          依据的已签署病历
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setSelectedRun('');
            }}
          >
            <option value="">请选择病历</option>
            {docs.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.title} · {formatTime(d.submitted_at || d.updated_at)}
              </option>
            ))}
          </select>
        </label>
      )}
      <details>
        <summary>补充说明或回答 Agent 的问题</summary>
        <textarea
          aria-label="补充给 Agent 的信息"
          value={clarification}
          onChange={(e) => setClarification(e.target.value)}
          placeholder="补充时间、任务条件或需要核实的重点，然后重新分析"
        />
      </details>
      {dirty && (
        <p className="panel-note">请先保存当前修改，再核查最新病历。</p>
      )}
      {!actor && (
        <p className="panel-note">
          尚未填写医生身份，Agent 自动分析未启动。
          <button
            type="button"
            className="text-button"
            onClick={() => {
              document
                .getElementById('actor-id')
                ?.scrollIntoView({ block: 'center' });
              document.getElementById('actor-id')?.focus();
            }}
          >
            填写医生身份
          </button>
          后会自动分析；已有报告可直接查看。
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!loaded && <p>正在读取历史分析…</p>}
      {filtered.length > 1 && (
        <label>
          分析版本
          <select
            value={run?.run_id || ''}
            onChange={(e) => setSelectedRun(e.target.value)}
          >
            {filtered.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {formatTime(r.created_at)} · {statuses[r.status]}
              </option>
            ))}
          </select>
        </label>
      )}
      {run && (
        <>
          <p role="status">
            {statuses[run.status]} · {formatTime(run.created_at)}
            {run.provider && ` · ${run.provider} / ${run.model}`}
          </p>
          {waiting && (
            <p className="panel-note">
              后台正在执行，可离开本页稍后查看；长时间排队时请检查 Worker。
            </p>
          )}
          {run.error && (
            <p className="error-text" role="alert">
              {run.error}
            </p>
          )}
          {run.stale && run.status !== 'ACTIVE' && (
            <p className="care-stale">
              资料或病历已变化，此结果是旧版本，请重新分析。此前审核意见仅对应旧版本。
            </p>
          )}
          {run.result && (
            <>
              <p className="care-summary">{run.result.summary}</p>
              {run.result.findings.map((item, i) => (
                <article className="care-item" key={i}>
                  <strong>
                    {categories[item.category]}：{item.text}
                  </strong>
                  <details>
                    <summary>查看原始依据（{item.source_ids.length}）</summary>
                    {item.source_ids.map((id) => {
                      const source = run.sources?.find((s) => s.id === id);
                      return (
                        <div key={id}>
                          <b>{source?.label || id}</b>
                          {source?.time && (
                            <small> · {formatTime(source.time)}</small>
                          )}
                          <pre>{source?.text || '来源未找到'}</pre>
                        </div>
                      );
                    })}
                  </details>
                  {mode !== 'PLAN' &&
                    (run.reviews?.[String(i)] ? (
                      <p>已记录医生意见：{run.reviews[String(i)].reason}</p>
                    ) : (
                      <div className="workspace-actions">
                        <button
                          type="button"
                          className="text-button"
                          disabled={
                            busy ||
                            !actor ||
                            !reason.trim() ||
                            run.stale ||
                            dirty
                          }
                          onClick={() =>
                            void decide({
                              action: 'RESOLVE',
                              item_key: String(i),
                              reason,
                            })
                          }
                        >
                          已核实并记录
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          disabled={
                            busy ||
                            !actor ||
                            !reason.trim() ||
                            run.stale ||
                            dirty
                          }
                          onClick={() =>
                            void decide({
                              action: 'DISMISS',
                              item_key: String(i),
                              reason,
                            })
                          }
                        >
                          标记不适用
                        </button>
                      </div>
                    ))}
                </article>
              ))}
              {mode !== 'PLAN' && !!run.result.findings.length && (
                <label>
                  核实或不采纳的说明
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="填写说明，再对相应项目记录审核决定"
                  />
                </label>
              )}
              {mode === 'PLAN' && (
                <PlanEditor
                  key={`${run.run_id}:${run.revision}`}
                  run={run}
                  busy={busy || !actor}
                  onDecide={decide}
                />
              )}
            </>
          )}
          <details className="care-trace">
            <summary>Agent 执行记录与计划变更</summary>
            <ol>
              {run.trace.map((step, i) => (
                <li key={i}>
                  <b>{tools[step.tool] || step.tool}</b>：{step.reason}（读取{' '}
                  {step.count} 条）
                </li>
              ))}
            </ol>
            {run.history.map((h, i) => (
              <p key={i}>
                {formatTime(h.time)} · {h.actor}：{h.reason}
              </p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
