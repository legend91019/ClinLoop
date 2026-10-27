import { useEffect, useState } from 'react';
import { Plus, Search, Users } from 'lucide-react';
import { api } from '../api/client';
import type { Clinician } from '../api/types';
import type { PatientCreate, PatientProfile } from '../api/workspaceTypes';

const emptyPatient: PatientCreate = {
  display_name: '',
  sex: '未说明',
  age: 40,
  ethnicity: '未记录',
  marital_status: '未记录',
  birthplace: '',
  occupation: '',
  admitted_at: null,
  ward: '模拟病区',
  bed: '',
  chief_complaint: '',
  history: '',
  allergies: '未记录',
};

export default function PatientDirectory({
  selected,
  encounter,
  actor,
  onSelect,
  onResolve,
  revision,
}: {
  selected: string;
  encounter?: string;
  actor: Clinician | null;
  onSelect: (patient: PatientProfile) => void;
  onResolve?: (patient: PatientProfile) => void;
  revision: number;
}) {
  const [patients, setPatients] = useState<PatientProfile[]>([]);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(emptyPatient);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .listPatients(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setPatients(rows);
        setError('');
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reload, revision]);
  // Resolve a directly opened URL to its patient profile without replacing it.
  useEffect(() => {
    const current = patients.find(
      (p) =>
        p.patient_id === selected &&
        (!encounter || p.encounter_id === encounter),
    );
    if (current) (onResolve || onSelect)(current);
  }, [patients, selected, encounter, onSelect, onResolve]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!actor) return;
    setBusy(true);
    setError('');
    try {
      const patient = await api.createPatient(form, actor);
      setShowCreate(false);
      setForm(emptyPatient);
      setReload((r) => r + 1);
      onSelect(patient);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function seed() {
    if (!actor) return;
    setBusy(true);
    setError('');
    try {
      await api.seedPatients(actor);
      setReload((r) => r + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const shown = patients.filter((p) =>
    `${p.display_name} ${p.patient_id} ${p.ward} ${p.bed}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section
      className="patient-directory"
      id="patients"
      aria-labelledby="patients-title"
    >
      <div className="workspace-section-heading">
        <div>
          <p className="eyebrow">PATIENT DIRECTORY</p>
          <h2 id="patients-title">
            <Users size={20} /> 我的患者{' '}
            <span className="count">{patients.length}</span>
          </h2>
          <p>先选择患者，再撰写记录和安排跟进。所有患者均为虚构。</p>
        </div>
        <div className="workspace-actions">
          <button className="button" disabled={!actor || busy} onClick={seed}>
            导入 6 位模拟患者
          </button>
          <button
            className="button primary"
            disabled={!actor || busy}
            onClick={() => setShowCreate(!showCreate)}
          >
            <Plus size={16} /> 新建模拟患者
          </button>
        </div>
      </div>
      {!actor && (
        <p className="panel-note">
          在上方填写医生 ID 并选择角色，即可新建患者、撰写记录和创建任务。
        </p>
      )}
      <label className="directory-search">
        <Search size={16} />
        <span className="sr-only">搜索患者</span>
        <input
          aria-label="搜索患者"
          placeholder="搜索姓名、患者 ID、病区或床号"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}{' '}
          <button
            className="text-button"
            onClick={() => setReload((r) => r + 1)}
          >
            重新加载患者
          </button>
        </p>
      )}
      {showCreate && (
        <form className="patient-create-form" onSubmit={create}>
          <h3>新建模拟患者</h3>
          <div className="workspace-form-grid">
            <label>
              患者姓名
              <input
                required
                maxLength={200}
                value={form.display_name}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
                placeholder="例如：王晓（模拟）"
              />
            </label>
            <label>
              性别
              <select
                value={form.sex}
                onChange={(e) =>
                  setForm({
                    ...form,
                    sex: e.target.value as PatientCreate['sex'],
                  })
                }
              >
                <option>未说明</option>
                <option>男</option>
                <option>女</option>
              </select>
            </label>
            <label>
              年龄
              <input
                required
                type="number"
                min={0}
                max={120}
                value={form.age}
                onChange={(e) =>
                  setForm({ ...form, age: Number(e.target.value) })
                }
              />
            </label>
            <label>
              病区
              <input
                required
                value={form.ward}
                onChange={(e) => setForm({ ...form, ward: e.target.value })}
              />
            </label>
            <label>
              民族
              <input
                maxLength={64}
                value={form.ethnicity || ''}
                onChange={(e) =>
                  setForm({ ...form, ethnicity: e.target.value })
                }
                placeholder="例如：汉族"
              />
            </label>
            <label>
              婚姻状况
              <select
                aria-label="婚姻状况"
                value={form.marital_status || '未记录'}
                onChange={(e) =>
                  setForm({
                    ...form,
                    marital_status: e.target
                      .value as PatientCreate['marital_status'],
                  })
                }
              >
                {['未记录', '未婚', '已婚', '离异', '丧偶', '其他'].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  ),
                )}
              </select>
            </label>
            <label>
              出生地
              <input
                maxLength={200}
                value={form.birthplace || ''}
                onChange={(e) =>
                  setForm({ ...form, birthplace: e.target.value })
                }
                placeholder="例如：四川省成都市"
              />
            </label>
            <label>
              职业
              <input
                maxLength={200}
                value={form.occupation || ''}
                onChange={(e) =>
                  setForm({ ...form, occupation: e.target.value })
                }
                placeholder="例如：教师"
              />
            </label>
            <label>
              入院时间（本机时间）
              <input
                type="datetime-local"
                aria-label="入院时间（本机时间）"
                value={
                  form.admitted_at
                    ? new Date(
                        new Date(form.admitted_at).getTime() -
                          new Date(form.admitted_at).getTimezoneOffset() *
                            60000,
                      )
                        .toISOString()
                        .slice(0, 16)
                    : ''
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    admitted_at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : null,
                  })
                }
              />
              <small>不填写时使用创建档案的时间</small>
            </label>
            <label>
              床号
              <input
                maxLength={32}
                value={form.bed}
                onChange={(e) => setForm({ ...form, bed: e.target.value })}
              />
            </label>
            <label>
              过敏史
              <input
                maxLength={1000}
                value={form.allergies}
                onChange={(e) =>
                  setForm({ ...form, allergies: e.target.value })
                }
              />
            </label>
          </div>
          <label>
            主诉
            <textarea
              maxLength={2000}
              value={form.chief_complaint}
              onChange={(e) =>
                setForm({ ...form, chief_complaint: e.target.value })
              }
            />
          </label>
          <label>
            既往史
            <textarea
              maxLength={5000}
              value={form.history}
              onChange={(e) => setForm({ ...form, history: e.target.value })}
            />
          </label>
          <div className="workspace-actions">
            <button className="button primary" disabled={busy}>
              创建患者档案
            </button>
            <button
              type="button"
              className="button"
              onClick={() => setShowCreate(false)}
            >
              取消
            </button>
          </div>
        </form>
      )}
      {loading ? (
        <p role="status">正在加载患者…</p>
      ) : (
        <div className="patient-cards">
          {shown.map((p) => (
            <button
              key={p.encounter_id}
              className={`patient-select-card ${selected === p.patient_id && (!encounter || encounter === p.encounter_id) ? 'selected' : ''}`}
              onClick={() => onSelect(p)}
            >
              <div className="card-top">
                <span className="patient-bed">
                  {p.bed ? `${p.bed} 床` : '未分床'}
                </span>
                <span className="patient-task-count">
                  {p.open_tasks} 项待办
                </span>
              </div>
              <strong>{p.display_name}</strong>
              <span>
                {p.sex} · {p.age} 岁 · {p.ward}
              </span>
              <p>{p.chief_complaint || '主诉待补充'}</p>
              <small>{p.patient_id}</small>
            </button>
          ))}
          {!shown.length && !error && (
            <p>
              {patients.length
                ? '没有匹配的患者。'
                : '尚无模拟患者，请导入示例或新建患者。'}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
