import { useState } from 'react';
import {
  Activity,
  ArrowRight,
  ClipboardList,
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
    page: 'patient-agent',
    title: '患者 Agent 助手',
    text: '审核候选任务，跟进结果与证据',
    icon: GitBranch,
  },
  {
    page: 'records',
    title: '病历与查房',
    text: '撰写、保存并提交患者记录',
    icon: FileText,
  },
  {
    page: 'followups',
    title: '患者跟进任务',
    text: '安排待办，填写处理结果',
    icon: ClipboardList,
  },
  {
    page: 'timeline',
    title: '患者时间线',
    text: '按时间回顾患者事件',
    icon: Timer,
  },
  {
    page: 'gaps',
    title: '流程缺口',
    text: '核对证据，审核待处理提示',
    icon: Activity,
  },
  {
    page: 'handoff',
    title: '交接草稿',
    text: '整理本次就诊的事实与待办',
    icon: Layers3,
  },
  {
    page: 'loops',
    title: '未闭环任务',
    text: '查看等待结果与处理中的工作',
    icon: Layers3,
  },
  {
    page: 'trace',
    title: 'Agent 运行轨迹',
    text: '回顾工具调用、证据和停止原因',
    icon: GitBranch,
  },
  {
    page: 'demo',
    title: '预设事件链演示',
    text: '体验 P-1001 的完整检验演示',
    icon: GitBranch,
  },
] as const;

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
      <div hidden={page !== 'overview'}>
        <div className="metrics">
          <div className="metric">
            <div className="metric-icon mint">
              <Layers3 size={19} />
            </div>
            <div>
              <p>未闭环任务</p>
              <strong>{active?.length ?? '—'}</strong>
            </div>
            <button className="text-button" onClick={() => onNavigate('loops')}>
              查看任务
            </button>
          </div>
          <div className="metric">
            <div className="metric-icon peach">
              <Activity size={19} />
            </div>
            <div>
              <p>待医生审核</p>
              <strong>{pending ?? '—'}</strong>
            </div>
            <button className="text-button" onClick={() => onNavigate('gaps')}>
              前往审核
            </button>
          </div>
          <div className="metric">
            <div className="metric-icon blue">
              <Timer size={19} />
            </div>
            <div>
              <p>窗口内事件</p>
              <strong>{timeline.data?.entries.length ?? '—'}</strong>
            </div>
            <button
              className="text-button"
              onClick={() => onNavigate('timeline')}
            >
              查看时间线
            </button>
          </div>
        </div>
      </div>
      {!profile && ['records', 'followups', 'patient-agent'].includes(page) && (
        <div className="page-empty">
          <h2>正在获取患者档案</h2>
          <p>如未能加载，请返回患者列表选择已建立档案的模拟患者。</p>
          <button className="button" onClick={() => onNavigate('patients')}>
            前往患者列表
          </button>
        </div>
      )}
      <div hidden={page !== 'overview'} className="patient-page-entries">
        {entries
          .filter((entry) => entry.page !== 'demo' || patient === 'P-1001')
          .map(({ page: target, title, text, icon: Icon }) => (
            <button
              key={target}
              className={`page-entry-card ${target === 'patient-agent' ? 'featured' : ''}`}
              onClick={() => onNavigate(target)}
            >
              <Icon size={22} />
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
              <ArrowRight size={18} />
            </button>
          ))}
      </div>
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
