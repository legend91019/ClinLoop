import { useEffect, useRef, useState } from 'react';
import { Bot, GitBranch, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import type { AgentRun, Clinician } from '../api/types';
import type {
  AgentCandidate,
  AgentWorkspace,
  PatientProfile,
} from '../api/workspaceTypes';
import { formatTime, label } from './shared';

const panels = {
  blood_culture_result: '血培养',
  susceptibility_result: '药敏',
  blood_count_result: '血常规',
  renal_function_result: '肾功能',
};
const errors: Record<string, string> = {
  DOCUMENT_TOO_MANY_CLAUSES:
    '记录内容较多，超出当前分析步数限制，请另写一份简明的随访记录。',
  DOCUMENT_ANALYSIS_TIMEOUT: '分析超时，请重试。',
};

export default function PatientAgentPanel({
  profile,
  actor,
  revision,
  onChanged,
  onWriteRecord,
}: {
  profile: PatientProfile;
  actor: Clinician | null;
  revision: number;
  onChanged: () => void;
  onWriteRecord?: () => void;
}) {
  const [data, setData] = useState<AgentWorkspace | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [panel, setPanel] = useState('blood_culture_result');
  const [result, setResult] = useState('');
  const [rejection, setRejection] = useState<{
    document: string;
    candidate: AgentCandidate;
  } | null>(null);
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState<{ loop: string; next: string | null } | null>(
    null,
  );
  const [trace, setTrace] = useState<AgentRun | null>(null);
  const callback = useRef(onChanged);
  const previous = useRef('');
  const pendingLab = useRef<{
    request_id: string;
    panel: string;
    result: string;
  } | null>(null);
  useEffect(() => {
    callback.current = onChanged;
  }, [onChanged]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let started = Date.now();
    async function poll() {
      try {
        const snapshot = await api.getAgentWorkspace(
          profile.patient_id,
          profile.encounter_id,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const signature = JSON.stringify(snapshot);
        if (previous.current && previous.current !== signature)
          callback.current();
        previous.current = signature;
        setData(snapshot);
        setLoadError('');
        if (
          snapshot.documents.some((doc) => doc.analysis?.status === 'QUEUED') &&
          Date.now() - started > 20000
        ) {
          setMessage(
            '分析仍在排队，请检查 Worker 是否运行；也可以稍后重新打开本患者。',
          );
        }
      } catch (e) {
        if (!controller.signal.aborted) setLoadError((e as Error).message);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
      started = 0;
    };
  }, [profile.patient_id, profile.encounter_id, revision, reload]);

  async function action(work: () => Promise<unknown>, text: string) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await work();
      setMessage(text);
      setReload((n) => n + 1);
      callback.current();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function review(
    document: string,
    candidate: AgentCandidate,
    verdict: 'ACCEPT' | 'REJECT',
    comment: string,
  ) {
    if (!actor) return;
    await action(
      async () => {
        await api.reviewAgentCandidate(
          profile.patient_id,
          document,
          candidate.candidate_id,
          verdict,
          comment,
          actor,
        );
        setRejection(null);
        setReason('');
      },
      verdict === 'ACCEPT'
        ? '已确认建议，Agent 任务已创建，后续结果到达后会继续跟进。'
        : '已驳回建议，决定及理由已保留。',
    );
  }
  async function showTrace(runId: string) {
    await action(async () => {
      const runs = await api.listPatientRuns(profile.patient_id);
      const run = runs.find((item) => item.run_id === runId);
      if (!run) throw new Error('运行轨迹尚未加载，请稍后重试');
      setTrace(run);
    }, '已加载本次 Agent 运行记录。');
  }
  async function submitLab(event: React.FormEvent) {
    event.preventDefault();
    if (!actor) return;
    const request = pendingLab.current || {
      request_id: crypto.randomUUID(),
      panel,
      result,
    };
    pendingLab.current = request;
    await action(async () => {
      await api.sendAgentLab(
        profile.patient_id,
        { encounter_id: profile.encounter_id, ...request },
        actor,
      );
      pendingLab.current = null;
      setResult('');
    }, '模拟结果已送入当前患者事件流，Agent 将核对项目、患者、就诊与证据来源。');
  }
  const tasks = data?.tasks || [];
  const pending =
    data?.documents.reduce(
      (sum, doc) =>
        sum +
        (doc.analysis?.candidates.filter((c) => c.status === 'PENDING')
          .length || 0),
      0,
    ) || 0;
  return (
    <section
      className="patient-agent-panel"
      id="patient-agent"
      aria-labelledby="patient-agent-title"
    >
      <div className="workspace-section-heading">
        <div>
          <p className="eyebrow">PATIENT WORKFLOW AGENT</p>
          <h2 id="patient-agent-title">
            <Bot size={23} /> 这位患者的 Agent 助手
          </h2>
          <p>
            读查房记录 → 提出候选任务 → 医生确认 → 等待结果并核对证据 →
            医生审核闭环。
          </p>
        </div>
        <span className="agent-mode">
          {data?.provider === 'mock'
            ? '本地确定性演示 · 未调用大模型'
            : data
              ? `配置来源：${data.provider}（实际来源见轨迹）`
              : '正在连接 Worker…'}
        </span>
      </div>
      <div className="agent-progress">
        <span>
          <Sparkles size={15} /> {pending} 项候选待确认
        </span>
        <span>
          {tasks.filter((t) => t.state === 'WAITING_EVENT').length} 项等待结果
        </span>
        <span>
          {tasks.filter((t) => t.state === 'RESULT_AVAILABLE').length}{' '}
          项结果待查看
        </span>
        <span>
          {tasks.filter((t) => t.state === 'RESOLVED').length} 项已闭环
        </span>
      </div>
      {!actor && (
        <p className="panel-note">
          先填写医生身份，再确认 Agent 建议或模拟结果到达。
        </p>
      )}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {loadError && (
        <p role="alert" className="error-text">
          Agent 状态加载失败：{loadError}
        </p>
      )}
      {message && (
        <p role="status" className="workspace-success">
          {message}
        </p>
      )}
      {!data?.documents.length && (
        <p className="agent-empty">
          先在病历与查房页写一份记录，例如“血培养结果出来后提醒我查看；补充患者过敏史”，提交后
          Agent 会自动分析。
        </p>
      )}
      <div className="agent-document-list">
        {onWriteRecord && (
          <button className="button" onClick={onWriteRecord}>
            前往撰写查房记录
          </button>
        )}
        {data?.documents.map((doc) => (
          <article className="agent-document" key={doc.document_id}>
            <div className="card-top">
              <strong>{doc.title}</strong>
              <span>
                {doc.analysis?.status === 'QUEUED'
                  ? 'Agent 分析排队中…'
                  : doc.analysis?.status === 'FAILED'
                    ? '分析未完成'
                    : doc.analysis
                      ? '分析完成'
                      : '尚未交给 Agent'}
              </span>
            </div>
            {(!doc.analysis || doc.analysis.status === 'FAILED') && (
              <button
                className="button"
                disabled={!actor || busy}
                onClick={() =>
                  actor &&
                  void action(
                    () =>
                      api.analyzePatientDocument(
                        profile.patient_id,
                        doc.document_id,
                        actor,
                      ),
                    '已提交分析，等待 Worker 处理。',
                  )
                }
              >
                {doc.analysis ? '重试 Agent 分析' : '让 Agent 分析这份记录'}
              </button>
            )}
            {doc.analysis?.error && (
              <p className="error-text">
                {errors[doc.analysis.error] ||
                  `分析失败（${doc.analysis.error}），未创建任务。`}
              </p>
            )}
            {doc.analysis?.status === 'READY' &&
              !doc.analysis.candidates.length && (
                <p className="panel-note">
                  未识别到明确待办。可另写一份明确包含随访要求的记录，或手动创建任务。
                </p>
              )}
            {doc.analysis?.candidates.map((candidate) => (
              <div className="agent-candidate" key={candidate.candidate_id}>
                <div className="card-top">
                  <strong>{candidate.proposal.goal}</strong>
                  <span>
                    {candidate.status === 'PENDING'
                      ? '待确认'
                      : candidate.status === 'ACCEPTED'
                        ? '已采纳'
                        : '已驳回'}{' '}
                    · {label(candidate.proposal.priority)}
                  </span>
                </div>
                <blockquote>原文：{candidate.source_text}</blockquote>
                <p>{candidate.proposal.rationale}</p>
                <p className="panel-note">
                  {candidate.proposal.intent_type === 'FOLLOW_RESULT'
                    ? `等待项目：${candidate.proposal.expected_evidence.map((key) => panels[key as keyof typeof panels] || key).join('、')}`
                    : '执行方式：医生人工跟进'}
                </p>
                {candidate.status === 'PENDING' && (
                  <div className="workspace-actions">
                    <button
                      className="button primary"
                      disabled={!actor || busy}
                      onClick={() =>
                        void review(
                          doc.document_id,
                          candidate,
                          'ACCEPT',
                          '医生确认创建此任务',
                        )
                      }
                    >
                      确认并创建任务
                    </button>
                    <button
                      className="button"
                      disabled={!actor || busy}
                      onClick={() => {
                        setRejection({ document: doc.document_id, candidate });
                        setReason('');
                      }}
                    >
                      驳回建议
                    </button>
                  </div>
                )}
                {candidate.review_reason && candidate.status === 'REJECTED' && (
                  <p>驳回原因：{candidate.review_reason}</p>
                )}
              </div>
            ))}
            {doc.analysis?.run_id && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void showTrace(doc.analysis!.run_id!)}
              >
                <GitBranch size={14} /> 查看本次分析轨迹
              </button>
            )}
          </article>
        ))}
      </div>
      {rejection && (
        <form
          className="task-update-form"
          onSubmit={(e) => {
            e.preventDefault();
            void review(
              rejection.document,
              rejection.candidate,
              'REJECT',
              reason,
            );
          }}
        >
          <label>
            驳回原因
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button className="button" disabled={busy || !reason.trim()}>
            确认驳回
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => setRejection(null)}
          >
            取消
          </button>
        </form>
      )}
      {!!tasks.length && (
        <div className="agent-active-tasks">
          <h3>Agent 持续跟进</h3>
          {tasks.map((task) => (
            <article className="managed-task" key={task.loop_id}>
              <div className="card-top">
                <strong>
                  {task.goal === 'Await susceptibility result'
                    ? '继续跟进药敏结果'
                    : task.goal}
                </strong>
                <span>{label(task.state)}</span>
              </div>
              {task.state === 'WAITING_EVENT' && (
                <p>
                  已挂起等待匹配结果。结果到达后由 Worker
                  自动唤醒并调用只读工具核对。
                </p>
              )}
              {task.result && (
                <div className="agent-result">
                  <strong>已核对的检验来源</strong>
                  <p>
                    {panels[
                      String(task.result.payload.panel) as keyof typeof panels
                    ] || String(task.result.payload.panel)}
                    ：{String(task.result.payload.result)}
                  </p>
                  <small>
                    {formatTime(task.result.source_time)} ·{' '}
                    {task.result.event_id}
                  </small>
                  <p>证据引用：{task.evidence_id}</p>
                </div>
              )}
              {task.state === 'RESULT_AVAILABLE' && (
                <div className="workspace-actions">
                  <button
                    className="button primary"
                    disabled={!actor || busy}
                    onClick={() => {
                      setAck({ loop: task.loop_id, next: null });
                      setReason('');
                    }}
                  >
                    查看后确认并闭环
                  </button>
                  {task.result?.payload.panel === 'blood_culture_result' && (
                    <button
                      className="button"
                      disabled={!actor || busy}
                      onClick={() => {
                        setAck({
                          loop: task.loop_id,
                          next: 'susceptibility_result',
                        });
                        setReason('');
                      }}
                    >
                      确认并继续跟进药敏
                    </button>
                  )}
                </div>
              )}
              {['PLANNED', 'IN_PROGRESS'].includes(task.state) && (
                <button
                  className="button"
                  disabled={!actor || busy}
                  onClick={() => {
                    setAck({ loop: task.loop_id, next: 'manual' });
                    setReason('');
                  }}
                >
                  填写处理结果并完成
                </button>
              )}
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    const runs = await api.getTrace(task.loop_id);
                    if (!runs.length)
                      throw new Error(
                        '此任务尚无事件运行轨迹，结果到达后会自动生成。',
                      );
                    setTrace(runs[runs.length - 1]);
                  }, '已加载任务的最近一次运行轨迹。')
                }
              >
                查看任务跟进轨迹
              </button>
              {task.state === 'RESOLVED' && (
                <p>医生已确认完成，记录与运行轨迹保留。</p>
              )}
            </article>
          ))}
        </div>
      )}
      {ack && (
        <form
          className="task-update-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!actor) return;
            void action(async () => {
              if (ack.next === 'manual') {
                const task = tasks.find((t) => t.loop_id === ack.loop)!;
                await api.updateManagedTask(
                  profile.patient_id,
                  task,
                  'RESOLVED',
                  reason,
                  actor,
                );
              } else
                await api.acknowledgeAgentResult(
                  profile.patient_id,
                  ack.loop,
                  reason,
                  ack.next,
                  actor,
                );
              setAck(null);
              setReason('');
            }, '医生处理记录已提交；结果随访由 Worker 复核后更新状态。');
          }}
        >
          <h3>
            {ack.next === 'susceptibility_result'
              ? '确认已查看，并建立药敏依赖任务'
              : '确认处理结果'}
          </h3>
          {ack.next !== 'manual' && (
            <p>
              此操作同时确认本任务的结果未响应提示；Worker
              核对原始证据后完成闭环。
            </p>
          )}
          <label>
            医生处理说明
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="请填写已核对的内容和处理结果"
            />
          </label>
          <div className="workspace-actions">
            <button
              className="button primary"
              disabled={busy || !reason.trim()}
            >
              确认提交处理结果
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => setAck(null)}
            >
              取消操作
            </button>
          </div>
        </form>
      )}
      <details className="agent-lab-entry">
        <summary>模拟当前患者的检验结果到达</summary>
        <p>用于验证事件驱动的自动唤醒。此处不会连接真实检验系统。</p>
        <form onSubmit={submitLab}>
          <div className="workspace-form-grid">
            <label>
              检验项目
              <select
                value={panel}
                disabled={!!pendingLab.current}
                onChange={(e) => setPanel(e.target.value)}
              >
                {Object.entries(panels).map(([key, name]) => (
                  <option value={key} key={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              模拟结果
              <input
                required
                maxLength={5000}
                value={result}
                disabled={!!pendingLab.current}
                placeholder="例如：模拟报告已回报，待医生核对"
                onChange={(e) => setResult(e.target.value)}
              />
            </label>
          </div>
          <button
            className="button"
            disabled={!actor || busy || !result.trim()}
          >
            {pendingLab.current ? '重试发送同一结果' : '发送当前患者模拟结果'}
          </button>
        </form>
      </details>
      {trace && (
        <div className="agent-inline-trace">
          <div className="card-top">
            <h3>本次 Agent 运行轨迹</h3>
            <button className="text-button" onClick={() => setTrace(null)}>
              收起轨迹
            </button>
          </div>
          <p>
            来源：{String(trace.trace_metadata?.provider)} · 模型：
            {String(trace.trace_metadata?.model)} · 停止原因：
            {label(trace.stop_reason || '')}
          </p>
          <ol>
            {trace.steps.map((step) => (
              <li key={step.step_id}>
                <strong>{step.kind}</strong> {step.reason}
                {step.tool_call && (
                  <small>
                    工具：{step.tool_call.tool_name} · 耗时{' '}
                    {step.tool_call.duration_ms} ms · 引用{' '}
                    {step.tool_call.result_ref}
                  </small>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
