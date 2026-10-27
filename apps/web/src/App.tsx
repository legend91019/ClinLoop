import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  ArrowLeft,
  CalendarClock,
  ClipboardList,
  FileText,
  GitBranch,
  HeartPulse,
  LayoutDashboard,
  Layers3,
  PanelLeftClose,
  Search,
  ShieldCheck,
  Stethoscope,
  UserRound,
} from 'lucide-react';
import type { Clinician } from './api/types';
import type { PatientProfile } from './api/workspaceTypes';
import PatientDirectory from './components/PatientDirectory';
import PatientWorkspace from './components/PatientWorkspace';
import {
  readLocation,
  workspaceUrl,
  type PatientPage,
  type WorkspaceLocation,
} from './navigation';
import './workspace.css';

const navigation = [
  {
    id: 'patients',
    title: '患者列表',
    icon: UserRound,
    description: '选择患者，或新建一份模拟档案。',
  },
  {
    id: 'overview',
    title: '患者概览',
    icon: LayoutDashboard,
    description: '查看当前患者资料与待办概况，选择本次工作。',
  },
  {
    id: 'patient-agent',
    title: '患者 Agent 助手',
    icon: GitBranch,
    description: '审核 Agent 建议，核对结果与证据，持续跟进。',
  },
  {
    id: 'records',
    title: '病历与查房',
    icon: FileText,
    description: '撰写和提交记录，保存后可随时继续编辑草稿。',
  },
  {
    id: 'followups',
    title: '患者跟进任务',
    icon: ClipboardList,
    description: '安排人工待办，记录进展与处理结果。',
  },
  {
    id: 'timeline',
    title: '患者时间线',
    icon: CalendarClock,
    description: '按时间回顾当前患者的记录与事件。',
  },
  {
    id: 'loops',
    title: '未闭环任务',
    icon: Layers3,
    description: '查看仍在等待结果或处理的工作事项。',
  },
  {
    id: 'gaps',
    title: '流程缺口',
    icon: Activity,
    description: '核对原始证据，接受或驳回待审核提示。',
  },
  {
    id: 'trace',
    title: 'Agent 运行轨迹',
    icon: GitBranch,
    description: '查看模型来源、工具调用、证据引用和停止原因。',
  },
  {
    id: 'handoff',
    title: '交接草稿',
    icon: ClipboardList,
    description: '整理本次就诊的已确认事实和未完成事项。',
  },
  {
    id: 'demo',
    title: '预设事件链演示',
    icon: GitBranch,
    description: '使用 P-1001 演示原有的检验随访流程。',
  },
] satisfies {
  id: PatientPage;
  title: string;
  icon: typeof UserRound;
  description: string;
}[];

export default function App() {
  const [location, setLocation] = useState(readLocation);
  const { patient, page } = location;
  const [patientInput, setPatientInput] = useState(patient);
  const [patientError, setPatientError] = useState('');
  const [actorId, setActorId] = useState('');
  const [role, setRole] = useState<Clinician['role'] | ''>('');
  const [navOpen, setNavOpen] = useState(false);
  const [profile, setProfile] = useState<PatientProfile>();
  const [directoryRevision, setDirectoryRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const selectedProfile =
    profile?.patient_id === patient &&
    (!location.encounter || profile.encounter_id === location.encounter)
      ? profile
      : undefined;
  const actor: Clinician | null =
    actorId.trim() && role ? { actor_id: actorId.trim(), role } : null;
  const current = navigation.find((item) => item.id === page)!;

  const transition = useCallback(
    (next: WorkspaceLocation, replace = false) => {
      const switchingPatient =
        next.patient !== patient ||
        (!!next.encounter &&
          next.encounter !== selectedProfile?.encounter_id &&
          next.encounter !== location.encounter);
      if (
        switchingPatient &&
        dirty &&
        !window.confirm('当前文书有未保存的内容，确定切换患者吗？')
      )
        return false;
      if (next.patient !== patient) setProfile(undefined);
      window.history[replace ? 'replaceState' : 'pushState'](
        null,
        '',
        workspaceUrl(next),
      );
      setLocation(next);
      setPatientInput(next.patient);
      setPatientError('');
      setNavOpen(false);
      window.scrollTo?.({ top: 0, behavior: 'instant' });
      return true;
    },
    [patient, selectedProfile?.encounter_id, location.encounter, dirty],
  );
  const navigate = (next: PatientPage) => {
    if (next !== page) transition({ ...location, page: next });
  };
  const selectPatient = useCallback(
    (next: PatientProfile) => {
      if (
        transition({
          patient: next.patient_id,
          encounter: next.encounter_id,
          page: 'overview',
        })
      )
        setProfile(next);
    },
    [transition],
  );
  const resolvePatient = useCallback((next: PatientProfile) => {
    setProfile(next);
  }, []);
  useEffect(() => {
    const handlePop = () => {
      const next = readLocation();
      const changedPatient =
        next.patient !== patient || next.encounter !== location.encounter;
      if (
        changedPatient &&
        dirty &&
        !window.confirm('当前文书有未保存的内容，确定切换患者吗？')
      ) {
        window.history.pushState(null, '', workspaceUrl(location));
        return;
      }
      if (next.patient !== patient) setProfile(undefined);
      setLocation(next);
      setPatientInput(next.patient);
      setPatientError('');
      setNavOpen(false);
      window.scrollTo?.({ top: 0, behavior: 'instant' });
    };
    window.addEventListener('popstate', handlePop);
    window.addEventListener('hashchange', handlePop);
    return () => {
      window.removeEventListener('popstate', handlePop);
      window.removeEventListener('hashchange', handlePop);
    };
  }, [patient, location, dirty]);
  function loadPatient(event: React.FormEvent) {
    event.preventDefault();
    if (!patientInput.trim()) {
      setPatientError('请填写患者 ID');
      return;
    }
    transition({
      patient: patientInput.trim(),
      encounter:
        patientInput.trim() === patient ? location.encounter : undefined,
      page: 'overview',
    });
  }
  return (
    <div id="console-shell" className="app-shell paged-workspace">
      <a className="skip-link" href="#main-content">
        跳到工作台内容
      </a>
      <aside className={`sidebar ${navOpen ? 'expanded' : ''}`}>
        <a
          className="brand"
          href={workspaceUrl({ ...location, page: 'overview' })}
          onClick={(e) => {
            if (
              !e.ctrlKey &&
              !e.metaKey &&
              !e.shiftKey &&
              !e.altKey &&
              e.button === 0
            ) {
              e.preventDefault();
              navigate('overview');
            }
          }}
        >
          <span className="brand-icon">
            <HeartPulse size={26} />
          </span>
          <span>
            ClinLoop<small>临床工作流连续性</small>
          </span>
        </a>
        <p className="nav-label">医生工作台</p>
        <nav aria-label="工作台导航">
          {navigation
            .filter((item) => item.id === 'patients' || item.id === 'overview')
            .map(({ id, title, icon: Icon }) => (
              <a
                key={id}
                className={
                  (page === 'patients' ? id === 'patients' : id === 'overview')
                    ? 'active'
                    : ''
                }
                href={workspaceUrl({ ...location, page: id })}
                aria-current={
                  (page === 'patients' ? id === 'patients' : id === 'overview')
                    ? 'page'
                    : undefined
                }
                onClick={(e) => {
                  if (
                    e.ctrlKey ||
                    e.metaKey ||
                    e.shiftKey ||
                    e.altKey ||
                    e.button !== 0
                  )
                    return;
                  e.preventDefault();
                  navigate(id);
                  setNavOpen(false);
                }}
              >
                <Icon size={19} />
                <span>{title}</span>
                {(page === 'patients'
                  ? id === 'patients'
                  : id === 'overview') && <span className="nav-dot" />}
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
            <strong>{current.title}</strong>
          </div>
          <span className="environment-badge">
            <span />
            合成数据演示
          </span>
        </header>
        <main id="main-content" className="main-content">
          {page !== 'patients' && page !== 'overview' && (
            <div className="patient-page-back">
              <button
                className="text-button"
                type="button"
                onClick={() => navigate('overview')}
              >
                <ArrowLeft size={17} /> 返回患者概览
              </button>
              <span>{selectedProfile?.display_name || '当前患者'}</span>
            </div>
          )}
          <div className="page-intro compact-page-intro">
            <div>
              <p className="eyebrow">PATIENT WORKSPACE</p>
              <h1>{current.title}</h1>
              <p>{current.description}</p>
            </div>
            {page === 'overview' && (
              <button className="button" onClick={() => navigate('patients')}>
                切换患者
              </button>
            )}
          </div>
          <div className="disclaimer">
            <ShieldCheck size={17} />
            <span>
              仅使用合成数据 ·
              工程验证，不构成临床有效性证明。请由医生核验事实与待办。
            </span>
          </div>
          <div
            hidden={page === 'overview'}
            className="workspace-controls compact-workspace-controls"
          >
            <form className="patient-search" onSubmit={loadPatient}>
              <label htmlFor="patient">患者 ID</label>
              <div>
                <Search size={17} />
                <input
                  id="patient"
                  value={patientInput}
                  onChange={(e) => setPatientInput(e.target.value)}
                  placeholder="输入患者 ID"
                  aria-invalid={!!patientError}
                  aria-describedby={patientError ? 'patient-error' : undefined}
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
                    onChange={(e) => setActorId(e.target.value)}
                    placeholder="请填写医生标识"
                    autoComplete="off"
                  />
                </label>
                <label htmlFor="actor-role">
                  临床角色
                  <select
                    id="actor-role"
                    value={role}
                    onChange={(e) =>
                      setRole(e.target.value as Clinician['role'] | '')
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
          {dirty && page !== 'records' && (
            <div className="retained-draft" role="status">
              当前患者有未保存的文书，页面切换已为你保留。
              <button
                className="text-button"
                onClick={() => navigate('records')}
              >
                返回继续编辑
              </button>
            </div>
          )}
          <div hidden={page !== 'patients'}>
            <PatientDirectory
              selected={patient}
              encounter={location.encounter || selectedProfile?.encounter_id}
              actor={actor}
              onSelect={selectPatient}
              onResolve={resolvePatient}
              revision={directoryRevision}
            />
          </div>
          <PatientWorkspace
            key={`${patient}:${selectedProfile?.encounter_id || ''}`}
            patient={patient}
            page={page}
            actor={actor}
            profile={selectedProfile}
            onNavigate={navigate}
            onChanged={() => setDirectoryRevision((v) => v + 1)}
            onDirtyChange={setDirty}
          />
          <footer className="page-footer">
            <span>ClinLoop · 临床工作流连续性</span>
            <span>合成数据 · 证据可追溯 · 医生审核</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
