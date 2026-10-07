import { useEffect, useState } from 'react';
import {
  Activity,
  ArrowRight,
  CalendarClock,
  CircleCheck,
  ClipboardList,
  FileText,
  GitBranch,
  HeartPulse,
  Layers3,
  PanelLeftClose,
  RefreshCw,
  Search,
  ShieldCheck,
  Stethoscope,
  Timer,
  UserRound,
} from 'lucide-react';
import type { Clinician, ReviewResponse } from './api/types';
import { usePatientWorkflow } from './hooks/usePatientWorkflow';
import PatientTimeline from './components/PatientTimeline';
import OpenLoopsPanel from './components/OpenLoopsPanel';
import WorkflowGapsPanel from './components/WorkflowGapsPanel';
import AgentTracePanel from './components/AgentTracePanel';
import HandoffDraftPanel from './components/HandoffDraftPanel';
import EvidenceDrawer from './components/EvidenceDrawer';
import SyntheticEventPanel from './components/SyntheticEventPanel';
import './workspace.css';

const getPatient = () =>
  new URLSearchParams(window.location.search).get('patient')?.trim() ||
  'P-1001';
const navigation = [
  { id: 'timeline', title: '患者时间线', icon: CalendarClock },
  { id: 'loops', title: '未闭环任务', icon: Layers3 },
  { id: 'gaps', title: '流程缺口', icon: Activity },
  { id: 'trace', title: 'Agent 运行轨迹', icon: GitBranch },
  { id: 'handoff', title: '交接草稿', icon: ClipboardList },
];

function Workspace({
  patient,
  actor,
  hours,
  setHours,
}: {
  patient: string;
  actor: Clinician | null;
  hours: number;
  setHours: (hours: number) => void;
}) {
  const { timeline, loops, findings } = usePatientWorkflow(patient, hours);
  const [encounter, setEncounter] = useState('');
  const [encounterSource, setEncounterSource] =
    useState('手动输入或从原始证据中选用');
  const [selectedTrace, setSelectedTrace] = useState('');
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const selected = loops.data?.some((loop) => loop.loop_id === selectedTrace)
    ? selectedTrace
    : '';
  const pending = findings.data?.filter(
    (item) => item.requires_review && item.review_status === 'PENDING_REVIEW',
  ).length;
  const active = loops.data?.filter(
    (loop) => !['RESOLVED', 'CANCELLED'].includes(loop.state),
  );
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
    <>
      <div className="patient-banner">
        <div className="patient-avatar">
          <UserRound size={24} />
        </div>
        <div className="patient-heading">
          <p className="eyebrow">CURRENT WORKSPACE</p>
          <h2>
            患者 <span>{patient}</span>
          </h2>
          <p>合成病例 · 工作流连续性验证</p>
        </div>
        <div className="encounter-control">
          <label htmlFor="encounter">就诊 ID</label>
          <input
            id="encounter"
            value={encounter}
            onChange={(event) => {
              setEncounter(event.target.value);
              setEncounterSource('医生手动输入，请核对患者归属');
            }}
            placeholder="请确认当前患者的就诊 ID"
            aria-describedby="encounter-help"
          />
          <p id="encounter-help">{encounterSource}</p>
        </div>
        <button
          className="icon-button refresh-all"
          aria-label="刷新患者数据"
          onClick={() => {
            timeline.retry();
            loops.retry();
            findings.retry();
          }}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <div className="metrics">
        <div className="metric">
          <div className="metric-icon mint">
            <Layers3 size={19} />
          </div>
          <div>
            <p>未闭环任务</p>
            <strong>{active?.length ?? '—'}</strong>
          </div>
          <span className="metric-caption">持续追踪</span>
        </div>
        <div className="metric">
          <div className="metric-icon peach">
            <Activity size={19} />
          </div>
          <div>
            <p>待医生审核</p>
            <strong>{pending ?? '—'}</strong>
          </div>
          <span className="metric-caption">证据绑定</span>
        </div>
        <div className="metric">
          <div className="metric-icon blue">
            <Timer size={19} />
          </div>
          <div>
            <p>窗口内事件</p>
            <strong>{timeline.data?.entries.length ?? '—'}</strong>
          </div>
          <span className="metric-caption">最近 {hours} 小时</span>
        </div>
      </div>
      <div className="workflow-ribbon">
        <span>
          <CircleCheck size={15} />
          意图
        </span>
        <ArrowRight size={13} />
        <span>医嘱</span>
        <ArrowRight size={13} />
        <span>执行</span>
        <ArrowRight size={13} />
        <span>结果</span>
        <ArrowRight size={13} />
        <span>医生响应</span>
        <ArrowRight size={13} />
        <span>
          <FileText size={15} />
          交接
        </span>
        <small>每一步，都有据可循</small>
      </div>
      <SyntheticEventPanel
        patient={patient}
        timeline={timeline.data?.entries}
      />
      <div className="workspace-grid">
        <PatientTimeline
          resource={timeline}
          hours={hours}
          setHours={setHours}
        />
        <OpenLoopsPanel resource={loops} onTrace={setSelectedTrace} />
        <WorkflowGapsPanel
          resource={findings}
          actor={actor}
          onEvidence={setEvidenceId}
          onReviewed={reviewed}
        />
        <AgentTracePanel
          patient={patient}
          loops={loops}
          selected={selected}
          onSelect={setSelectedTrace}
        />
        <HandoffDraftPanel
          patient={patient}
          encounter={encounter}
          actor={actor}
          findings={findings}
          onFindings={findings.setData}
        />
      </div>
      {evidenceId && (
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
    </>
  );
}

export default function App() {
  const [patient, setPatient] = useState(getPatient);
  const [patientInput, setPatientInput] = useState(patient);
  const [patientError, setPatientError] = useState('');
  const [hours, setHours] = useState(24);
  const [actorId, setActorId] = useState('');
  const [role, setRole] = useState<Clinician['role'] | ''>('');
  const [activeNav, setActiveNav] = useState('timeline');
  const [navOpen, setNavOpen] = useState(false);
  const actor: Clinician | null =
    actorId.trim() && role ? { actor_id: actorId.trim(), role } : null;
  useEffect(() => {
    const handlePop = () => {
      const id = getPatient();
      setPatient(id);
      setPatientInput(id);
      setPatientError('');
    };
    window.addEventListener('popstate', handlePop);
    return () => window.removeEventListener('popstate', handlePop);
  }, []);
  function loadPatient(event: React.FormEvent) {
    event.preventDefault();
    const id = patientInput.trim();
    if (!id) {
      setPatientError('请填写患者 ID');
      return;
    }
    setPatientError('');
    setPatient(id);
    const url = new URL(window.location.href);
    url.searchParams.set('patient', id);
    window.history.replaceState(null, '', url);
  }
  return (
    <>
      <div id="console-shell" className="app-shell">
        <a className="skip-link" href="#main-content">
          跳到工作台内容
        </a>
        <aside className={`sidebar ${navOpen ? 'expanded' : ''}`}>
          <a className="brand" href="#main-content">
            <span className="brand-icon">
              <HeartPulse size={26} />
            </span>
            <span>
              ClinLoop<small>临床工作流连续性</small>
            </span>
          </a>
          <p className="nav-label">医生工作台</p>
          <nav aria-label="工作台导航">
            {navigation.map(({ id, title, icon: Icon }) => (
              <a
                key={id}
                className={activeNav === id ? 'active' : ''}
                href={`#${id}`}
                aria-current={activeNav === id ? 'location' : undefined}
                onClick={() => {
                  setActiveNav(id);
                  setNavOpen(false);
                }}
              >
                <Icon size={19} />
                <span>{title}</span>
                {activeNav === id && <span className="nav-dot" />}
              </a>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <ShieldCheck size={22} />
            <strong>证据先行，医生把关</strong>
            <p>追踪流程 · 保留来源 · 审核留痕</p>
            <span>
              ClinLoop MVP <span className="demo-tag">DEMO</span>
            </span>
          </div>
        </aside>
        <div className="main-area">
          <header className="topbar">
            <div className="breadcrumb">
              <button
                className="icon-button mobile-nav-button"
                aria-label="切换导航"
                aria-expanded={navOpen}
                onClick={() => setNavOpen(!navOpen)}
              >
                <PanelLeftClose size={19} />
              </button>
              <Stethoscope size={17} />
              <span>临床工作台</span>
              <span className="breadcrumb-slash">/</span>
              <strong>连续性总览</strong>
            </div>
            <span className="environment-badge">
              <span />
              合成数据演示
            </span>
          </header>
          <main id="main-content" className="main-content">
            <div className="page-intro">
              <div>
                <p className="eyebrow">CLINICAL CONTINUITY CONSOLE</p>
                <h1>每一项临床意图，都有下文。</h1>
                <p>追踪未闭环任务，核对证据，让每一次交接清晰可续。</p>
              </div>
              <span className="intro-mark">
                <GitBranch size={24} />
              </span>
            </div>
            <div className="disclaimer">
              <ShieldCheck size={17} />
              <span>
                仅使用合成数据 ·
                工程验证，不构成临床有效性证明。请由医生核验事实与待办。
              </span>
            </div>
            <div className="workspace-controls">
              <form className="patient-search" onSubmit={loadPatient}>
                <label htmlFor="patient">患者 ID</label>
                <div>
                  <Search size={17} />
                  <input
                    id="patient"
                    value={patientInput}
                    onChange={(event) => setPatientInput(event.target.value)}
                    placeholder="输入患者 ID"
                    aria-invalid={!!patientError}
                    aria-describedby={
                      patientError ? 'patient-error' : undefined
                    }
                  />
                  <button className="button primary" type="submit">
                    加载患者
                  </button>
                </div>
                {patientError && (
                  <p id="patient-error" className="error-text" role="alert">
                    {patientError}
                  </p>
                )}
              </form>
              <fieldset className="identity-controls">
                <legend>
                  临床身份 <span>{actor ? '已填写' : '写操作前请填写'}</span>
                </legend>
                <div>
                  <label htmlFor="actor-id">
                    医生 ID
                    <input
                      id="actor-id"
                      value={actorId}
                      onChange={(event) => setActorId(event.target.value)}
                      placeholder="请填写医生标识"
                      autoComplete="off"
                    />
                  </label>
                  <label htmlFor="actor-role">
                    临床角色
                    <select
                      id="actor-role"
                      value={role}
                      onChange={(event) =>
                        setRole(event.target.value as Clinician['role'] | '')
                      }
                    >
                      <option value="">请选择角色</option>
                      <option value="PHYSICIAN">医生 · PHYSICIAN</option>
                      <option value="CLINICIAN">临床人员 · CLINICIAN</option>
                    </select>
                  </label>
                </div>
                <p>演示身份用于审计归属；生产环境需接入认证。</p>
              </fieldset>
            </div>
            <Workspace
              key={patient}
              patient={patient}
              actor={actor}
              hours={hours}
              setHours={setHours}
            />
            <footer className="page-footer">
              <span>ClinLoop · 临床工作流连续性</span>
              <span>合成数据 · 证据可追溯 · 医生审核</span>
            </footer>
          </main>
        </div>
      </div>
    </>
  );
}
