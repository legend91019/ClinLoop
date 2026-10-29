import { useState } from 'react';
import {
  ArrowRight,
  FileText,
  GitBranch,
  Layers3,
  RefreshCw,
  Timer,
  UserRound,
} from 'lucide-react';
import type { Clinician, ReviewResponse } from '../api/types';
import type { PatientProfile } from '../api/workspaceTypes';
import type { PatientPage } from '../navigation';
import { usePatientWorkflow } from '../hooks/usePatientWorkflow';
import PatientRecords from './PatientRecords';
import PatientAgentPanel from './PatientAgentPanel';
import PatientTimeline from './PatientTimeline';
import OpenLoopsPanel from './OpenLoopsPanel';
import WorkflowGapsPanel from './WorkflowGapsPanel';
import AgentTracePanel from './AgentTracePanel';
import HandoffDraftPanel from './HandoffDraftPanel';
import EvidenceDrawer from './EvidenceDrawer';
import SyntheticEventPanel from './SyntheticEventPanel';

const entries = [
  {
    page: 'records',
    title: '病历与查房',
    text: '问诊转录、Agent 撰写、医生审核签署',
    icon: FileText,
  },
  {
    page: 'patient-agent',
    title: 'Agent 任务中心',
    text: '集中确认建议、安排待办、审核提醒与跟进结果',
    icon: GitBranch,
  },
  {
    page: 'timeline',
    title: '患者时间线',
    text: '按时间回顾患者事件',
    icon: Timer,
  },
  {
    page: 'handoff',
    title: '交接草稿',
    text: '整理本次就诊的事实与待办',
    icon: Layers3,
  },
] as const;

const taskViews = [
  {
    page: 'patient-agent',
    title: 'Agent 建议与结果',
    text: '确认候选任务，核对新回报结果并闭环。',
  },
  {
    page: 'followups',
    title: '医生待办',
    text: '安排人工跟进事项，处理首次查房等待办。',
  },
  {
    page: 'gaps',
    title: '提醒审核',
    text: '查看需医生审核的提示，并核对原始证据。',
  },
] as const;
const taskPages: PatientPage[] = [
  'patient-agent',
  'followups',
  'gaps',
  'loops',
  'trace',
  'demo',
];

export default function PatientWorkspace({
  patient,
  page,
  actor,
  profile,
  onNavigate,
  onChanged,
  onDirtyChange,
}: {
  patient: string;
  page: PatientPage;
  actor: Clinician | null;
  profile?: PatientProfile;
  onNavigate: (page: PatientPage) => void;
  onChanged: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [hours, setHours] = useState(24);
  const { timeline, loops, findings } = usePatientWorkflow(patient, hours);
  const [encounter, setEncounter] = useState(profile?.encounter_id || '');
  const [encounterSource, setEncounterSource] =
    useState('手动输入或从原始证据中选用');
  const [selectedTrace, setSelectedTrace] = useState('');
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [visited, setVisited] = useState<PatientPage[]>([page]);
  if (!visited.includes(page)) setVisited([...visited, page]);
  const opened = (target: PatientPage) =>
    visited.includes(target) || page === target;
  const active = loops.data?.filter(
    (loop) => !['RESOLVED', 'CANCELLED'].includes(loop.state),
  );
  const pending = findings.data?.filter(
    (item) => item.requires_review && item.review_status === 'PENDING_REVIEW',
  ).length;
  const selected = loops.data?.some((loop) => loop.loop_id === selectedTrace)
    ? selectedTrace
    : '';
  function refresh() {
    timeline.retry();
    loops.retry();
    findings.retry();
    setRevision((v) => v + 1);
    onChanged();
  }
  function reviewed(response: ReviewResponse) {
    if (findings.data)
      findings.setData(
        findings.data.map((item) =>
          item.finding_id === response.finding_id
            ? {
                ...item,
                review_status: response.review_status,
                requires_review:
                  response.action === 'ACCEPT' ? false : item.requires_review,
              }
            : item,
        ),
      );
    loops.retry();
  }
  return (
    <div hidden={page === 'patients'} className="patient-workspace-pages">
      <div
        hidden={page === 'overview'}
        className="patient-banner compact-patient-banner"
      >
        <div className="patient-avatar">
          <UserRound size={24} />
        </div>
        <div className="patient-heading">
          <p className="eyebrow">CURRENT PATIENT</p>
          <h2>
            {profile?.display_name || '患者'} <span>{patient}</span>
          </h2>
          <p>
            {profile
              ? `${profile.sex} · ${profile.age} 岁 · ${profile.ward}${profile.bed ? ` · ${profile.bed} 床` : ''}`
              : '合成病例 · 工作流连续性验证'}
          </p>
        </div>
        <div className="encounter-control">
          <label htmlFor="encounter">就诊 ID</label>
          <input
            id="encounter"
            value={encounter}
            readOnly={!!profile}
            onChange={(e) => {
              setEncounter(e.target.value);
              setEncounterSource('医生手动输入，请核对患者归属');
            }}
            placeholder="请确认当前患者的就诊 ID"
            aria-describedby="encounter-help"
          />
          <p id="encounter-help">
            {profile ? '已关联当前患者就诊' : encounterSource}
          </p>
        </div>
        <button
          className="icon-button refresh-all"
          aria-label="刷新患者数据"
          onClick={refresh}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      {profile && (
        <div hidden={!['overview', 'records', 'followups'].includes(page)}>
          <PatientRecords
            profile={profile}
            actor={actor}
            page={page}
            refreshRevision={revision}
            onNavigate={onNavigate}
            onDirtyChange={onDirtyChange}
            onChanged={refresh}
          />
        </div>
      )}
      {!profile && ['records', 'followups', 'patient-agent'].includes(page) && (
        <div className="page-empty">
          <h2>正在获取患者档案</h2>
          <p>如未能加载，请返回患者列表选择已建立档案的模拟患者。</p>
          <button className="button" onClick={() => onNavigate('patients')}>
            前往患者列表
          </button>
        </div>
      )}
      <nav
        hidden={page !== 'overview'}
        className="patient-page-entries"
        aria-label="患者功能"
      >
        {entries.map(({ page: target, title, text, icon: Icon }) => (
          <button
            key={target}
            className={`page-entry-card ${target === 'patient-agent' ? 'featured' : ''}`}
            onClick={() => onNavigate(target)}
          >
            <Icon size={22} />
            <div>
              <strong>{title}</strong>
              <p>{text}</p>
              {target === 'patient-agent' && (
                <small className="page-entry-summary">
                  {active?.length ?? '—'} 项跟进中 · {pending ?? '—'}{' '}
                  条待审核提醒
                </small>
              )}
              {target === 'timeline' && (
                <small className="page-entry-summary">
                  最近 {hours} 小时 · {timeline.data?.entries.length ?? '—'}{' '}
                  条事件
                </small>
              )}
            </div>
            <ArrowRight size={18} />
          </button>
        ))}
      </nav>
      {taskPages.includes(page) && (
        <section className="task-center-navigation" aria-label="任务中心">
          <strong>Agent 任务中心</strong>
          <nav aria-label="任务中心导航" className="task-center-tabs">
            {taskViews.map((view) => (
              <button
                type="button"
                key={view.page}
                className={`button ${page === view.page ? 'primary' : ''}`}
                aria-current={page === view.page ? 'page' : undefined}
                onClick={() => onNavigate(view.page)}
              >
                {view.title}
              </button>
            ))}
          </nav>
          {taskViews.find((view) => view.page === page) && (
            <p>{taskViews.find((view) => view.page === page)?.text}</p>
          )}
          <details open={['loops', 'trace', 'demo'].includes(page)}>
            <summary>更多记录与演示</summary>
            <div className="workspace-actions">
              <button
                type="button"
                className="text-button"
                aria-current={page === 'loops' ? 'page' : undefined}
                onClick={() => onNavigate('loops')}
              >
                任务状态明细
              </button>
              <button
                type="button"
                className="text-button"
                aria-current={page === 'trace' ? 'page' : undefined}
                onClick={() => onNavigate('trace')}
              >
                Agent 运行轨迹
              </button>
              {patient === 'P-1001' && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => onNavigate('demo')}
                >
                  预设事件链演示
                </button>
              )}
            </div>
          </details>
        </section>
      )}
      {profile && opened('patient-agent') && (
        <div hidden={page !== 'patient-agent'}>
          <PatientAgentPanel
            profile={profile}
            actor={actor}
            revision={revision}
            onChanged={refresh}
            onWriteRecord={() => onNavigate('records')}
          />
        </div>
      )}
      <div className="patient-single-page" hidden={page !== 'timeline'}>
        {opened('timeline') && (
          <PatientTimeline
            resource={timeline}
            hours={hours}
            setHours={setHours}
          />
        )}
      </div>
      <div className="patient-single-page" hidden={page !== 'loops'}>
        {opened('loops') && (
          <OpenLoopsPanel
            resource={loops}
            onTrace={(id) => {
              setSelectedTrace(id);
              onNavigate('trace');
            }}
          />
        )}
      </div>
      <div className="patient-single-page" hidden={page !== 'gaps'}>
        {opened('gaps') && (
          <WorkflowGapsPanel
            resource={findings}
            actor={actor}
            onEvidence={setEvidenceId}
            onReviewed={reviewed}
          />
        )}
      </div>
      <div className="patient-single-page" hidden={page !== 'trace'}>
        {opened('trace') && (
          <AgentTracePanel
            key={`${patient}:${revision}`}
            patient={patient}
            loops={loops}
            selected={selected}
            onSelect={setSelectedTrace}
          />
        )}
      </div>
      <div className="patient-single-page" hidden={page !== 'handoff'}>
        {opened('handoff') && (
          <HandoffDraftPanel
            patient={patient}
            encounter={encounter}
            actor={actor}
            findings={findings}
            onFindings={findings.setData}
          />
        )}
      </div>
      <div className="patient-single-page" hidden={page !== 'demo'}>
        {opened('demo') &&
          (patient === 'P-1001' ? (
            <SyntheticEventPanel patient={patient} onRefresh={refresh} />
          ) : (
            <p className="page-empty">
              预设事件链仅用于 P-1001。其他患者请使用“患者 Agent
              助手”中的结果模拟功能。
            </p>
          ))}
      </div>
      {evidenceId && page === 'gaps' && (
        <EvidenceDrawer
          key={evidenceId}
          id={evidenceId}
          patient={patient}
          onClose={() => setEvidenceId(null)}
          onEncounter={(id) => {
            setEncounter(id);
            setEncounterSource('已从当前患者的原始证据记录中选用');
            setEvidenceId(null);
          }}
        />
      )}
    </div>
  );
}
