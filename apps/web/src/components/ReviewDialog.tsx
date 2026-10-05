import { useState } from 'react';
import { api, isClinician } from '../api/client';
import type {
  Clinician,
  FindingResponse,
  ReviewAction,
  ReviewResponse,
} from '../api/types';
import { useAlive } from '../hooks/usePatientWorkflow';
import { Modal } from './shared';

export default function ReviewDialog({
  finding,
  action,
  actor,
  onClose,
  onReviewed,
}: {
  finding: FindingResponse;
  action: ReviewAction;
  actor: Clinician | null;
  onClose: () => void;
  onReviewed: (response: ReviewResponse) => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useAlive();
  const verb = action === 'ACCEPT' ? '接受' : '驳回';
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!isClinician(actor)) {
      setError('请先填写医生 ID 并选择临床角色');
      return;
    }
    if (action === 'REJECT' && !reason.trim()) {
      setError('驳回必须填写非空理由');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await api.reviewFinding(
        finding.finding_id,
        action,
        reason,
        actor,
      );
      if (alive.current) onReviewed(response);
    } catch (error) {
      if (alive.current)
        setError(error instanceof Error ? error.message : '审核失败，请重试');
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  return (
    <Modal title={`${verb}流程缺口`} onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="modal-content">
        <p className="claim-block">{finding.claim}</p>
        <p className="panel-note">
          审核将追加审计记录，原始描述与证据会保留。接受仅记录审核决定，任务状态由后端规则管理。
        </p>
        <p className="identity-line">
          审核人：{actor?.actor_id} · {actor?.role}
        </p>
        <label htmlFor="review-reason">
          审核理由
          <span className="optional">
            {action === 'REJECT' ? '必填' : '选填'}
          </span>
        </label>
        <textarea
          aria-label="审核理由"
          aria-required={action === 'REJECT'}
          id="review-reason"
          rows={4}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={busy}
          aria-describedby={error ? 'review-error' : undefined}
          aria-invalid={!!error}
        />
        {error && (
          <p id="review-error" className="error-text" role="alert">
            {error}
          </p>
        )}
        <footer className="actions">
          <button
            className="button secondary"
            type="button"
            onClick={onClose}
            disabled={busy}
          >
            取消
          </button>
          <button
            className={`button ${action === 'REJECT' ? 'danger' : 'primary'}`}
            disabled={busy || !isClinician(actor)}
          >
            {busy ? '正在记录…' : `确认${verb}`}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
