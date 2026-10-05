import { useState } from 'react';
import { FilePlus2, Save, ShieldCheck, FolderOpen } from 'lucide-react';
import { api, isClinician } from '../api/client';
import type {
  Clinician,
  FindingResponse,
  HandoffResponse,
  HandoffText,
} from '../api/types';
import { useAlive, type Resource } from '../hooks/usePatientWorkflow';
import { Badge, Modal, Section } from './shared';

const fields: { key: keyof HandoffText; title: string; help: string }[] = [
  { key: 'situation', title: 'S · 当前情况', help: '记录已确认的当前情况' },
  {
    key: 'background',
    title: 'B · 相关背景',
    help: '与本次交接相关的已确认背景',
  },
  {
    key: 'assessment',
    title: 'A · 流程评估',
    help: '区分已确认事实与待确认事项',
  },
  {
    key: 'recommendation',
    title: 'R · 待跟进事项',
    help: '交接备注、负责人和下一次检查安排',
  },
];
const pickText = (report: HandoffResponse): HandoffText => ({
  situation: report.situation,
  background: report.background,
  assessment: report.assessment,
  recommendation: report.recommendation,
});
const hasPendingReview = (findings: FindingResponse[]) =>
  findings.some(
    (finding) =>
      finding.requires_review &&
      !['ACCEPTED', 'REJECTED', 'EDITED'].includes(finding.review_status),
  );

export default function HandoffDraftPanel({
  patient,
  encounter,
  actor,
  findings,
  onFindings,
}: {
  patient: string;
  encounter: string;
  actor: Clinician | null;
  findings: Resource<FindingResponse[]>;
  onFindings: (items: FindingResponse[]) => void;
}) {
  const [report, setReport] = useState<HandoffResponse | null>(null);
  const [text, setText] = useState<HandoffText | null>(null);
  const [reportId, setReportId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmSeal, setConfirmSeal] = useState(false);
  const alive = useAlive();
  const identityReady = isClinician(actor);
  const editable = report?.status === 'DRAFT';
  const dirty =
    !!report &&
    !!text &&
    fields.some((field) => report[field.key] !== text[field.key]);
  const reviewUnknown = findings.loading || !!findings.error || !findings.data;
  const pending = !!findings.data && hasPendingReview(findings.data);
  const blockReason = !identityReady
    ? '请先填写医生 ID 并选择临床角色'
    : reviewUnknown
      ? '审核状态尚未确认，请先加载或重试流程缺口'
      : pending
        ? '存在未审核事项，请先完成医生审核'
        : dirty
          ? '有未保存的修改，请先保存草稿'
          : !editable
            ? '此报告已锁定，仅可查看'
            : '';

  function validateReport(
    result: HandoffResponse,
    id?: string,
    expectedEncounter?: string,
  ) {
    if (result.patient_id !== patient)
      throw new Error('交接报告与当前患者不匹配，已阻止展示');
    if (id && result.handoff_id !== id)
      throw new Error('交接报告 ID 不匹配，已阻止展示');
    if (expectedEncounter && result.encounter_id !== expectedEncounter)
      throw new Error('交接报告与选定就诊不匹配，已阻止展示');
    return result;
  }
  async function operation(
    work: () => Promise<HandoffResponse>,
    message: string,
  ) {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await work();
      if (alive.current) {
        setReport(result);
        setText(pickText(result));
        setReportId(result.handoff_id);
        setNotice(message);
        setConfirmSeal(false);
      }
    } catch (error) {
      if (alive.current) {
        setError(error instanceof Error ? error.message : '操作失败，请重试');
        setConfirmSeal(false);
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function create() {
    if (!isClinician(actor) || !encounter.trim()) return;
    const selectedEncounter = encounter.trim();
    void operation(
      async () =>
        validateReport(
          await api.createHandoffDraft(patient, selectedEncounter, actor),
          undefined,
          selectedEncounter,
        ),
      '交接草稿已生成',
    );
  }
  function load(event: React.FormEvent) {
    event.preventDefault();
    if (!reportId.trim() || dirty) return;
    const id = reportId.trim();
    void operation(
      async () => validateReport(await api.getHandoff(id), id),
      '交接报告已加载',
    );
  }
  function save() {
    if (!report || !text || !editable || !isClinician(actor)) return;
    const currentReport = report;
    void operation(
      async () =>
        validateReport(
          await api.updateHandoff(currentReport.handoff_id, text, actor),
          currentReport.handoff_id,
          currentReport.encounter_id,
        ),
      '草稿已保存',
    );
  }
  function seal() {
    if (!report || !isClinician(actor) || blockReason) return;
    const currentReport = report;
    void operation(async () => {
      const current = await api.listFindings(patient);
      if (!alive.current) throw new Error('患者已切换');
      if (current.some((finding) => finding.patient_id !== patient))
        throw new Error('审核记录与当前患者不匹配');
      onFindings(current);
      if (hasPendingReview(current))
        throw new Error('存在新的未审核事项，请先完成医生审核');
      return validateReport(
        await api.sealHandoff(currentReport.handoff_id, actor),
        currentReport.handoff_id,
        currentReport.encounter_id,
      );
    }, '交接已封存');
  }
  return (
    <>
      <Section
        id="handoff"
        title="交接草稿"
        english="HANDOFF DRAFT / SBAR"
        aside={
          report ? (
            <Badge value={report.status} />
          ) : (
            <span className="subtle">医生确认后封存</span>
          )
        }
      >
        <div className="handoff-toolbar">
          <div>
            <p className="panel-note">
              基于后端证据生成。仅四个 SBAR
              文本字段可编辑；证据与任务关联由服务维护。
            </p>
            {!report && (
              <button
                className="button primary"
                onClick={create}
                disabled={busy || !identityReady || !encounter.trim()}
              >
                <FilePlus2 size={16} />
                {busy ? '正在加载…' : '生成交接草稿'}
              </button>
            )}
          </div>
          <form onSubmit={load} className="report-loader">
            <label htmlFor="handoff-id">交接报告 ID</label>
            <div>
              <input
                id="handoff-id"
                value={reportId}
                placeholder="输入已有报告 ID"
                onChange={(event) => setReportId(event.target.value)}
                disabled={busy || dirty}
              />
              <button
                type="submit"
                className="button secondary"
                disabled={busy || dirty || !reportId.trim()}
              >
                <FolderOpen size={16} />
                打开交接报告
              </button>
            </div>
          </form>
        </div>
        {!identityReady && (
          <p className="warning-note">
            请先填写医生 ID 并选择临床角色，才能生成、保存或封存交接。
          </p>
        )}
        {!report && !encounter.trim() && (
          <p className="panel-note">
            请填写就诊 ID，或在证据抽屉中核对原始记录后选用就诊 ID。
          </p>
        )}
        {notice && (
          <p className="success-text" role="status">
            {notice}
          </p>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error} · 可重试当前操作
          </p>
        )}
        {report && text ? (
          <>
            <div className="handoff-metadata">
              <span>{report.handoff_id}</span>
              <span>患者 {report.patient_id}</span>
              <span>就诊 {report.encounter_id}</span>
              {dirty && <span className="dirty-mark">有未保存的修改</span>}
            </div>
            <div className="handoff-grid">
              {fields.map((field) => (
                <div className="sbar-field" key={field.key}>
                  <label htmlFor={`sbar-${field.key}`}>{field.title}</label>
                  <p className="panel-note" id={`help-${field.key}`}>
                    {field.help}
                  </p>
                  <textarea
                    id={`sbar-${field.key}`}
                    rows={4}
                    value={text[field.key]}
                    readOnly={!editable || !identityReady}
                    disabled={busy}
                    aria-describedby={`help-${field.key}`}
                    onChange={(event) => {
                      setText({ ...text, [field.key]: event.target.value });
                      setNotice('');
                    }}
                  />
                </div>
              ))}
            </div>
            <div className="handoff-context">
              <div>
                <h3>已确认事实</h3>
                {report.confirmed_items.length ? (
                  <ul>
                    {report.confirmed_items.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="panel-note">尚无医生确认事实</p>
                )}
              </div>
              <div>
                <h3>待确认 / 待跟进</h3>
                {report.pending_items.length ? (
                  <ul>
                    {report.pending_items.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="panel-note">报告中暂无待跟进事项</p>
                )}
              </div>
            </div>
            <details className="protected-links" open>
              <summary>证据与任务关联 · 只读</summary>
              <dl className="compact-dl">
                <div>
                  <dt>任务 IDs</dt>
                  <dd>
                    {report.loop_ids.map((id) => (
                      <code key={id}>{id}</code>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>证据 IDs</dt>
                  <dd>
                    {report.evidence_ids.map((id) => (
                      <code key={id}>{id}</code>
                    ))}
                  </dd>
                </div>
              </dl>
            </details>
            {editable && (
              <footer className="handoff-footer">
                <p
                  className={blockReason ? 'warning-text' : 'panel-note'}
                  id="seal-block-reason"
                >
                  {blockReason || '所有待审核事项已处理。封存后文本将锁定。'}
                </p>
                <div className="actions">
                  <button
                    className="button secondary"
                    onClick={save}
                    disabled={busy || !identityReady || !dirty}
                  >
                    <Save size={16} />
                    保存草稿
                  </button>
                  <button
                    className="button primary"
                    disabled={busy || !!blockReason}
                    aria-describedby="seal-block-reason"
                    onClick={() => setConfirmSeal(true)}
                  >
                    <ShieldCheck size={16} />
                    封存交接
                  </button>
                </div>
              </footer>
            )}
          </>
        ) : (
          <div className="handoff-empty">
            <FilePlus2 size={30} />
            <h3>让交接延续每一项待办</h3>
            <p>先确认患者、就诊与证据，再生成可审核的 SBAR 草稿。</p>
          </div>
        )}
      </Section>
      {confirmSeal && (
        <Modal
          title="封存交接报告"
          onClose={() => setConfirmSeal(false)}
          busy={busy}
        >
          <div className="modal-content">
            <p>
              封存后，四个 SBAR
              文本字段将锁定。系统会再次检查当前患者的待审核事项。
            </p>
            <p className="identity-line">
              {report?.handoff_id} · {patient} · {report?.encounter_id}
            </p>
            <footer className="actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setConfirmSeal(false)}
              >
                取消
              </button>
              <button
                className="button primary"
                disabled={busy || !!blockReason}
                onClick={seal}
              >
                {busy ? '正在检查并封存…' : '确认封存'}
              </button>
            </footer>
          </div>
        </Modal>
      )}
    </>
  );
}
