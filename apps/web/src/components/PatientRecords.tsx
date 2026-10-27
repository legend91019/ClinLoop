import { useEffect, useState } from 'react';
import { ClipboardPlus, FilePenLine, Plus } from 'lucide-react';
import { api } from '../api/client';
import type { Clinician } from '../api/types';
import type {
  ClinicalDocument,
  DocumentKind,
  ManagedTask,
  PatientProfile,
} from '../api/workspaceTypes';
import { formatTime, label } from './shared';
import InterviewComposer from './InterviewComposer';
import FirstRoundReminder from './FirstRoundReminder';

const kindLabels: Record<DocumentKind, string> = {
  ADMISSION: '入院病历',
  ROUND: '查房记录',
  PROGRESS: '病程记录',
};
const taskStates: Record<string, string> = {
  PLANNED: '待跟进',
  IN_PROGRESS: '进行中',
  RESOLVED: '已完成',
  CANCELLED: '已取消',
};
function template(kind: DocumentKind, profile: PatientProfile) {
  return kind === 'ADMISSION'
    ? `主诉：${profile.chief_complaint}\n\n现病史：\n\n既往史：${profile.history}\n\n过敏史：${profile.allergies}\n\n体格检查：\n\n辅助检查：\n\n入院评估：\n\n后续安排：`
    : kind === 'ROUND'
      ? '查房时间：\n\n主观情况（患者描述）：\n\n客观观察与检查：\n\n本次评估：\n\n后续安排与待跟进事项：'
      : '病情变化：\n\n新增检查与结果：\n\n本次评估：\n\n后续安排：';
}

export default function PatientRecords({
  profile,
  actor,
  onChanged,
  onDirtyChange,
  page = 'all',
  onNavigate,
  refreshRevision = 0,
}: {
  profile: PatientProfile;
  actor: Clinician | null;
  onChanged: () => void;
  onDirtyChange: (dirty: boolean) => void;
  page?: string;
  onNavigate?: (page: 'records' | 'followups' | 'patient-agent') => void;
  refreshRevision?: number;
}) {
  const patient = profile.patient_id;
  const encounter = profile.encounter_id;
  const [documents, setDocuments] = useState<ClinicalDocument[]>([]);
  const [tasks, setTasks] = useState<ManagedTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [revision, setRevision] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [current, setCurrent] = useState<ClinicalDocument | undefined>();
  const [kind, setKind] = useState<DocumentKind>('ROUND');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [dirty, setDirty] = useState(false);
  const [interviewDirty, setInterviewDirty] = useState(false);
  const [signatureName, setSignatureName] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState('');
  const [priority, setPriority] = useState('NORMAL');
  const [owner, setOwner] = useState(actor?.actor_id || '');
  const [due, setDue] = useState('');
  const [sourceDocument, setSourceDocument] = useState('');
  const [taskFilter, setTaskFilter] = useState('active');
  const [updating, setUpdating] = useState<{
    task: ManagedTask;
    state: string;
  } | null>(null);
  const [reason, setReason] = useState('');
  useEffect(() => {
    onDirtyChange(dirty || interviewDirty);
    return () => onDirtyChange(false);
  }, [dirty, interviewDirty, onDirtyChange]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (dirty || interviewDirty) event.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty, interviewDirty]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      api.listDocuments(patient, encounter, controller.signal),
      api.listManagedTasks(patient, encounter, controller.signal),
    ])
      .then(([docs, rows]) => {
        if (!controller.signal.aborted) {
          setDocuments(docs);
          setTasks(rows);
          setLoadError('');
        }
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setLoadError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [patient, encounter, revision, refreshRevision]);
  const viewOnly = current?.status === 'SUBMITTED';
  function openDocument(
    document?: ClinicalDocument,
    newKind: DocumentKind = 'ROUND',
  ) {
    if (
      dirty &&
      !window.confirm('当前文书有未保存的内容，确定放弃并打开其他记录吗？')
    )
      return false;
    setCurrent(document);
    setKind(document?.kind || newKind);
    setTitle(document?.title || kindLabels[newKind]);
    setContent(document?.content || template(newKind, profile));
    setDirty(false);
    setEditorOpen(true);
    setError('');
    setMessage('');
    setSignatureName('');
    setConfirmed(false);
    requestAnimationFrame(() =>
      window.document
        .getElementById('clinical-document-editor')
        ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }),
    );
    return true;
  }
  async function save(submit: boolean) {
    if (!actor) {
      setError('请先在上方填写医生 ID 并选择临床角色，再保存记录。');
      document.getElementById('actor-id')?.focus();
      return;
    }
    if (
      submit &&
      current?.generation &&
      (!signatureName.trim() || !confirmed)
    ) {
      setError('请填写医生签名，并确认已核对原文、检查记录及病历。');
      return;
    }
    if (
      submit &&
      !window.confirm('提交后该记录将锁定，并进入当前患者时间线。确认提交吗？')
    )
      return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const saved = await api.saveDocument(
        patient,
        { encounter_id: encounter, kind, title, content },
        actor,
        current,
      );
      setCurrent(saved);
      setDirty(false);
      const result = submit
        ? await api.submitDocument(
            patient,
            saved,
            actor,
            signatureName.trim() && confirmed
              ? { signature_name: signatureName.trim(), confirmed }
              : undefined,
          )
        : saved;
      setCurrent(result);
      setRevision((v) => v + 1);
      onChanged();
      setMessage(
        submit
          ? '记录已提交，Agent 已排队分析，可前往 Agent 助手核对候选任务。'
          : '草稿已保存，可以稍后继续编辑。',
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function createTask(event: React.FormEvent) {
    event.preventDefault();
    if (!actor) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api.createManagedTask(
        patient,
        {
          encounter_id: encounter,
          goal,
          priority,
          owner: owner.trim() || actor.actor_id,
          due_at: due ? new Date(due).toISOString() : null,
          source_document_id: sourceDocument || null,
        },
        actor,
      );
      setGoal('');
      setDue('');
      setSourceDocument('');
      setRevision((v) => v + 1);
      onChanged();
      setMessage('跟进任务已创建；高优先级未完成任务会进入交班草稿。');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function updateTask(event: React.FormEvent) {
    event.preventDefault();
    if (!actor || !updating) return;
    setBusy(true);
    setError('');
    try {
      await api.updateManagedTask(
        patient,
        updating.task,
        updating.state,
        reason,
        actor,
      );
      setUpdating(null);
      setReason('');
      setRevision((v) => v + 1);
      onChanged();
      setMessage('任务状态已更新，处理说明已留存。');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const visibleTasks = tasks.filter(
    (task) =>
      taskFilter === 'all' || !['RESOLVED', 'CANCELLED'].includes(task.state),
  );
  return (
    <div className="patient-records">
      <section
        hidden={page !== 'all' && page !== 'overview'}
        className="patient-profile basic-profile-card"
        aria-label="患者档案"
      >
        <div>
          <p className="eyebrow">PATIENT INFORMATION</p>
          <h2>基本信息</h2>
          <p>当前患者的入院基本资料</p>
        </div>
        <dl className="basic-info-grid">
          <div>
            <dt>姓名</dt>
            <dd>{profile.display_name}</dd>
          </div>
          <div>
            <dt>性别</dt>
            <dd>{profile.sex}</dd>
          </div>
          <div>
            <dt>民族</dt>
            <dd>{profile.ethnicity || '未记录'}</dd>
          </div>
          <div>
            <dt>年龄</dt>
            <dd>{profile.age} 岁</dd>
          </div>
          <div>
            <dt>婚姻状况</dt>
            <dd>{profile.marital_status || '未记录'}</dd>
          </div>
          <div>
            <dt>出生地</dt>
            <dd>{profile.birthplace || '未记录'}</dd>
          </div>
          <div>
            <dt>职业</dt>
            <dd>{profile.occupation || '未记录'}</dd>
          </div>
          <div>
            <dt>入院时间</dt>
            <dd>
              {profile.admitted_at
                ? new Intl.DateTimeFormat('zh-CN', {
                    timeZone: 'Asia/Shanghai',
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                  }).format(new Date(profile.admitted_at))
                : '未记录'}
            </dd>
          </div>
        </dl>
      </section>
      <div hidden={!['all', 'overview', 'records', 'followups'].includes(page)}>
        <FirstRoundReminder
          profile={profile}
          revision={revision + refreshRevision}
          onOpen={() => {
            onNavigate?.('records');
            requestAnimationFrame(() =>
              document
                .getElementById('round-transcription')
                ?.scrollIntoView({ behavior: 'smooth' }),
            );
          }}
        />
      </div>
      <div
        hidden={page !== 'all' && page !== 'overview'}
        className="patient-workflow-guide"
      >
        <strong>这位患者的工作流程</strong>
        <span>① 撰写记录并保存草稿</span>
        <span>② 核对后提交</span>
        <span>③ 确认 Agent 候选任务</span>
        <span>④ 记录处理结果并交班</span>
      </div>
      {!actor && page !== 'overview' && (
        <p className="panel-note">
          请在上方填写医生身份，启用文书保存和任务操作。
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="workspace-success" role="status">
          {message}
          {current?.status === 'SUBMITTED' && (
            <button
              className="text-button"
              type="button"
              onClick={() => onNavigate?.('patient-agent')}
            >
              前往 Agent 助手
            </button>
          )}
        </p>
      )}
      {loadError && (
        <p className="error-text" role="alert">
          {loadError}{' '}
          <button
            className="text-button"
            onClick={() => setRevision((v) => v + 1)}
          >
            重新加载记录
          </button>
        </p>
      )}
      <section
        className="records-section"
        id="records"
        hidden={page !== 'all' && page !== 'records'}
        aria-labelledby="records-title"
      >
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">CLINICAL DOCUMENTS</p>
            <h2 id="records-title">
              <FilePenLine size={20} /> 病历与查房记录
            </h2>
            <p>填写并保存草稿；提交后保留原文，需要补充时新建病程记录。</p>
          </div>
          <div className="workspace-actions">
            <button
              className="button"
              disabled={busy}
              onClick={() => {
                if (!openDocument(undefined, 'ROUND')) return;
                setTitle('查房随访记录');
                setContent(
                  '后续安排：血培养结果出来后提醒我查看；补充患者过敏史。',
                );
                setDirty(true);
              }}
            >
              试写 Agent 查房示例
            </button>
            {(['ADMISSION', 'ROUND', 'PROGRESS'] as DocumentKind[]).map(
              (type) => (
                <button
                  key={type}
                  className={`button ${type === 'ROUND' ? 'primary' : ''}`}
                  disabled={busy}
                  onClick={() => openDocument(undefined, type)}
                >
                  <Plus size={15} /> {kindLabels[type]}
                </button>
              ),
            )}
          </div>
        </div>
        <div id="round-transcription">
          <InterviewComposer
            profile={profile}
            actor={actor}
            active={page === 'records' || page === 'all'}
            onDirtyChange={setInterviewDirty}
            onReady={(doc) => {
              setDocuments((items) => [
                doc,
                ...items.filter((item) => item.document_id !== doc.document_id),
              ]);
              if (!dirty) openDocument(doc);
              else
                setMessage(
                  'Agent 草稿已生成，当前编辑内容已保留。请保存后从记录列表打开新草稿。',
                );
              setRevision((v) => v + 1);
            }}
          />
        </div>
        <div className="documents-layout">
          <div className="document-list">
            {loading ? (
              <p>正在加载记录…</p>
            ) : (
              documents.map((doc) => (
                <button
                  key={doc.document_id}
                  className={`document-item ${current?.document_id === doc.document_id ? 'selected' : ''}`}
                  disabled={busy}
                  onClick={() => openDocument(doc)}
                >
                  <span className="card-top">
                    <span>{kindLabels[doc.kind]}</span>
                    <span
                      className={`document-status ${doc.status.toLowerCase()}`}
                    >
                      {doc.status === 'DRAFT' ? '草稿' : '已提交'}
                    </span>
                  </span>
                  <strong>{doc.title}</strong>
                  <span className="document-preview">
                    {doc.content.slice(0, 75)}
                  </span>
                  <small>
                    {doc.author_id} · {formatTime(doc.updated_at)}
                  </small>
                </button>
              ))
            )}
            {!loading && !documents.length && !loadError && (
              <p className="panel-note">
                还没有文书，点击“入院病历”或“查房记录”开始。
              </p>
            )}
          </div>
          {editorOpen ? (
            <form
              className="document-editor"
              id="clinical-document-editor"
              onSubmit={(e) => {
                e.preventDefault();
                void save(false);
              }}
            >
              <div className="card-top">
                <strong>
                  {viewOnly ? '已提交记录 · 只读' : `编辑${kindLabels[kind]}`}
                </strong>
                <span>
                  {dirty
                    ? '有未保存的修改'
                    : current
                      ? `版本 ${current.revision}`
                      : '新草稿'}
                </span>
              </div>
              {current?.generation?.draft_mode === 'DEMO' && (
                <p className="panel-note">
                  这是本地文书格式演示，未调用真实模型。可在已保存对话中选择真实模型重新撰写。
                </p>
              )}
              {current?.generation && (
                <details className="source-dialogue">
                  <summary>核对医患原始对话与生成方式</summary>
                  <p>
                    生成器：{current.generation.provider} ·{' '}
                    {current.generation.model}
                    {current.generation.provider === 'mock' &&
                      '（本地模拟整理，按章节保留原文，不调用语言模型）'}
                  </p>
                  <pre>{current.generation.source_text}</pre>
                  <p>
                    {current.generation.writing_version === 2
                      ? '病历正文是独立的临床叙述。原始对话、检查与既往文书依据单独保留，请逐项核对。'
                      : '检查记录已附在病历正文中，保留来源与时间；请结合实际情况审核。'}
                  </p>
                </details>
              )}
              {current?.generation?.writing_version === 2 && (
                <details className="source-dialogue">
                  <summary>撰写依据、待补充信息与冲突</summary>
                  <p>
                    以下是初稿的来源映射；修改后的正文请重新对照资料核实。来源引用检查不代表医学内容已经核实。
                  </p>
                  {!!current.generation.missing_information?.length && (
                    <>
                      <strong>待医生补充</strong>
                      <ul>
                        {current.generation.missing_information.map(
                          (item, i) => (
                            <li key={i}>{item}</li>
                          ),
                        )}
                      </ul>
                    </>
                  )}
                  {!!current.generation.conflicts?.length && (
                    <>
                      <strong>待核对的来源冲突</strong>
                      <ul>
                        {current.generation.conflicts.map((item, i) => (
                          <li key={i}>
                            {item.text}（{item.source_ids.join('、')}）
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {current.generation.clinical_sections?.map((section) => (
                    <details key={section.heading}>
                      <summary>
                        {section.heading} · {section.sentences.length} 条叙述
                      </summary>
                      {section.sentences.map((sentence, i) => (
                        <article key={i}>
                          <p>{sentence.text}</p>
                          {sentence.source_ids.map((id) => {
                            const source = current.generation?.sources?.find(
                              (item) => item.source_id === id,
                            );
                            return (
                              <blockquote key={id}>
                                <strong>
                                  {id} · {source?.label}
                                </strong>
                                <pre>{source?.text}</pre>
                                {source?.ref && (
                                  <small>来源：{source.ref}</small>
                                )}
                              </blockquote>
                            );
                          })}
                        </article>
                      ))}
                    </details>
                  ))}
                </details>
              )}
              {!!current?.generation?.conflicts?.length && (
                <p className="error-text">
                  资料存在 {current.generation.conflicts.length}{' '}
                  处冲突，请在撰写依据中核对并修改正文。
                </p>
              )}
              {current?.signature && (
                <p className="workspace-success">
                  医生签名：{current.signature.name} ·{' '}
                  {current.signature.actor_id} ·{' '}
                  {formatTime(current.signature.signed_at)}
                </p>
              )}
              <label>
                记录标题
                <input
                  required
                  maxLength={200}
                  value={title}
                  disabled={busy}
                  readOnly={viewOnly}
                  onChange={(e) => {
                    setTitle(e.target.value);
                    setConfirmed(false);
                    setDirty(true);
                  }}
                />
              </label>
              <label>
                记录正文
                <textarea
                  aria-label="记录正文"
                  required
                  rows={15}
                  maxLength={30000}
                  value={content}
                  disabled={busy}
                  readOnly={viewOnly}
                  onChange={(e) => {
                    setContent(e.target.value);
                    setConfirmed(false);
                    setDirty(true);
                  }}
                />
              </label>
              {!viewOnly && (
                <fieldset className="signature-fields">
                  <legend>
                    医生审核签署
                    {current?.generation ? '（必填）' : '（可填写）'}
                  </legend>
                  <label>
                    医生签名
                    <input
                      value={signatureName}
                      maxLength={128}
                      disabled={busy}
                      onChange={(e) => {
                        setSignatureName(e.target.value);
                        setConfirmed(false);
                      }}
                    />
                  </label>
                  <label className="signature-confirm">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      disabled={busy}
                      onChange={(e) => setConfirmed(e.target.checked)}
                    />
                    我已核对原始对话、检查记录与病历内容，确认签署。
                  </label>
                </fieldset>
              )}
              {!viewOnly && (
                <div className="workspace-actions">
                  <button className="button" disabled={busy}>
                    保存草稿
                  </button>
                  <button
                    type="button"
                    className="button primary"
                    disabled={
                      busy ||
                      !title.trim() ||
                      !content.trim() ||
                      (!!current?.generation &&
                        (!signatureName.trim() || !confirmed))
                    }
                    onClick={() => void save(true)}
                  >
                    {busy
                      ? '处理中…'
                      : current?.generation
                        ? '医生签字确认并提交'
                        : '提交记录'}
                  </button>
                </div>
              )}
              {viewOnly && (
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    setSourceDocument(current.document_id);
                    onNavigate?.('followups');
                    requestAnimationFrame(() =>
                      document.getElementById('new-task-goal')?.focus(),
                    );
                  }}
                >
                  基于此记录创建任务
                </button>
              )}
            </form>
          ) : (
            <div className="document-empty">
              <FilePenLine size={30} />
              <h3>从一份清晰的记录开始</h3>
              <p>点击左侧草稿继续编辑，或新建一份入院病历、查房记录。</p>
              <p>模板只提供结构，记录内容由你填写。</p>
            </div>
          )}
        </div>
      </section>
      <section
        className="records-section"
        id="followups"
        hidden={page !== 'all' && page !== 'followups'}
        aria-labelledby="followups-title"
      >
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">FOLLOW-UP TASKS</p>
            <h2 id="followups-title">
              <ClipboardPlus size={20} /> 患者跟进任务
            </h2>
            <p>
              直接写下需要跟进的事项，由医生明确创建和更新，不依赖模型猜测。
            </p>
          </div>
          <label>
            显示
            <select
              value={taskFilter}
              onChange={(e) => setTaskFilter(e.target.value)}
            >
              <option value="active">未完成任务</option>
              <option value="all">全部任务</option>
            </select>
          </label>
        </div>
        <form className="new-task-form" onSubmit={createTask}>
          <label>
            需要跟进什么？
            <textarea
              id="new-task-goal"
              required
              maxLength={2000}
              placeholder="例如：核对这位患者本次血培养结果，并记录是否已查看"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
          </label>
          <div className="workspace-form-grid">
            <label>
              负责人
              <input
                maxLength={64}
                placeholder={actor?.actor_id || '医生 ID'}
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
              />
            </label>
            <label>
              优先级
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
              >
                <option value="LOW">低</option>
                <option value="NORMAL">普通</option>
                <option value="HIGH">高</option>
                <option value="CRITICAL">紧急</option>
              </select>
            </label>
            <label>
              截止时间（本机时间）
              <input
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
              />
            </label>
            <label>
              关联记录
              <select
                value={sourceDocument}
                onChange={(e) => setSourceDocument(e.target.value)}
              >
                <option value="">不关联文书</option>
                {documents
                  .filter((doc) => doc.status === 'SUBMITTED')
                  .map((doc) => (
                    <option key={doc.document_id} value={doc.document_id}>
                      {doc.title} · {formatTime(doc.submitted_at)}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <button
            className="button primary"
            disabled={!actor || busy || !goal.trim()}
          >
            创建跟进任务
          </button>
        </form>
        {updating && (
          <form className="task-update-form" onSubmit={updateTask}>
            <h3>
              {taskStates[updating.state]}：{updating.task.goal}
            </h3>
            <label>
              处理说明
              <textarea
                autoFocus
                required
                maxLength={2000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="记录做了什么、结果如何，或取消的原因"
              />
            </label>
            <div className="workspace-actions">
              <button
                className="button primary"
                disabled={busy || !reason.trim()}
              >
                确认更新状态
              </button>
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => setUpdating(null)}
              >
                取消操作
              </button>
            </div>
          </form>
        )}
        <div className="managed-task-list">
          {visibleTasks.map((task) => {
            const closed = ['RESOLVED', 'CANCELLED'].includes(task.state);
            const overdue =
              !closed &&
              !!task.due_at &&
              new Date(task.due_at).getTime() < Date.now();
            return (
              <article className="managed-task" key={task.loop_id}>
                <div className="card-top">
                  <span className={`task-state ${closed ? 'closed' : ''}`}>
                    {taskStates[task.state] || label(task.state)}
                  </span>
                  <span>
                    {label(task.priority)}
                    {overdue && (
                      <strong className="error-text"> · 已逾期</strong>
                    )}
                  </span>
                </div>
                <h3>{task.goal}</h3>
                <p>
                  负责人：{task.owner || '待分配'} · 截止：
                  {task.due_at ? formatTime(task.due_at) : '未设置'}
                </p>
                {task.source_document_id && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      const doc = documents.find(
                        (item) => item.document_id === task.source_document_id,
                      );
                      if (doc) {
                        if (openDocument(doc)) onNavigate?.('records');
                      }
                    }}
                  >
                    查看关联记录
                  </button>
                )}
                {task.system_managed && (
                  <p className="panel-note">
                    系统待办：签署查房记录后自动完成。
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => onNavigate?.('records')}
                    >
                      去查房
                    </button>
                  </p>
                )}
                {!closed && !task.system_managed && (
                  <div className="workspace-actions">
                    {task.state === 'PLANNED' && (
                      <button
                        className="button"
                        disabled={!actor || busy}
                        onClick={() => {
                          setUpdating({ task, state: 'IN_PROGRESS' });
                          setReason('');
                        }}
                      >
                        开始跟进
                      </button>
                    )}
                    <button
                      className="button"
                      disabled={!actor || busy}
                      onClick={() => {
                        setUpdating({ task, state: 'RESOLVED' });
                        setReason('');
                      }}
                    >
                      标记完成
                    </button>
                    <button
                      className="text-button"
                      disabled={!actor || busy}
                      onClick={() => {
                        setUpdating({ task, state: 'CANCELLED' });
                        setReason('');
                      }}
                    >
                      取消任务
                    </button>
                  </div>
                )}
                <details>
                  <summary>处理记录（{task.history.length}）</summary>
                  <ol>
                    {task.history.map((item, index) => (
                      <li key={index}>
                        <span>
                          {formatTime(item.created_at)} · {item.actor_id}
                        </span>
                        <p>{item.reason || item.action}</p>
                      </li>
                    ))}
                  </ol>
                </details>
              </article>
            );
          })}
          {!loading && !visibleTasks.length && !loadError && (
            <p className="panel-note">
              当前没有{taskFilter === 'active' ? '未完成' : ''}
              跟进任务，可在上方创建。
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
