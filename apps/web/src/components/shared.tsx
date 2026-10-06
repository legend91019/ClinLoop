import { createPortal } from 'react-dom';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { AlertCircle, LoaderCircle, RotateCcw, X } from 'lucide-react';
import type { Resource } from '../hooks/usePatientWorkflow';

export const labels: Record<string, string> = {
  NOTE_CREATED: '查房记录',
  ORDER_UPDATED: '医嘱更新',
  LAB_RESULT_CREATED: '检验结果',
  CONSULT_NOTE_CREATED: '会诊记录',
  PROGRESS_NOTE_CREATED: '病程记录',
  HANDOFF_STARTED: '交接开始',
  PATIENT_EVIDENCE_SUBMITTED: '患者提交证据',
  CREATED: '已创建',
  PLANNED: '已计划',
  ORDERED: '已下医嘱',
  ACTION_REQUESTED: '待执行',
  IN_PROGRESS: '执行中',
  RESULT_AVAILABLE: '结果已返回',
  ACKNOWLEDGED: '已确认',
  RESOLVED: '已闭环',
  WAITING_EVENT: '等待事件',
  OVERDUE: '已逾期',
  ORPHANED: '缺少关联',
  CONFLICTED: '存在冲突',
  STALE: '需更新',
  PENDING_REVIEW: '待审核',
  CANCELLED: '已取消',
  ACCEPTED: '已接受',
  REJECTED: '已驳回',
  EDITED: '已修改',
  DRAFT: '草稿',
  SEALED: '已封存',
  RESULT_WITHOUT_ACKNOWLEDGEMENT: '结果缺少医生确认',
  UNACKNOWLEDGED_CRITICAL_RESULT: '危急结果待确认',
  INTENT_WITHOUT_PLAN: '意图缺少计划',
  PLAN_WITHOUT_ORDER: '计划缺少医嘱',
  ORDER_WITHOUT_EXECUTION: '医嘱缺少执行',
  UNRESOLVED_HIGH_PRIORITY_LOOP: '高优先级任务未闭环',
  LOOP_MISSING_FROM_HANDOFF: '交接遗漏任务',
  CONFLICTING_EVIDENCE: '证据冲突',
  STALE_LOOP: '任务待更新',
  ORPHANED_LOOP: '任务缺少关联',
  SYSTEM_VERIFIED: '系统验证',
  CLINICIAN_CONFIRMED: '医生确认',
  PATIENT_REPORTED: '患者自述 · 待核验',
  PENDING_VERIFICATION: '待核验',
  UNVERIFIED: '未验证',
  WAITING_EXTERNAL_EVENT: '等待外部事件',
  REQUIRES_CLINICIAN_REVIEW: '需要医生审核',
  SUFFICIENT_EVIDENCE: '证据已充分',
  BUDGET_EXCEEDED: '达到运行预算',
  CONFLICTED_EVIDENCE: '证据存在冲突',
  MODEL_ERROR: '模型调用失败',
  HIGH: '高优先级',
  CRITICAL: '紧急',
  NORMAL: '常规',
  LOW: '低优先级',
};
export const label = (value: string) => labels[value] ?? value;
export function formatTime(value?: string | null) {
  if (!value) return '未设置';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(date);
}
export function Badge({ value, tone }: { value: string; tone?: string }) {
  const color =
    tone ??
    ([
      'HIGH',
      'CRITICAL',
      'PENDING_REVIEW',
      'PATIENT_REPORTED',
      'OVERDUE',
    ].includes(value)
      ? 'amber'
      : [
            'SEALED',
            'ACCEPTED',
            'SYSTEM_VERIFIED',
            'CLINICIAN_CONFIRMED',
            'RESOLVED',
          ].includes(value)
        ? 'green'
        : 'neutral');
  return (
    <span className={`badge ${color}`} title={value}>
      {label(value)}
    </span>
  );
}
export function ResourceState<T>({
  resource,
  empty,
  isEmpty,
}: {
  resource: Resource<T>;
  empty: string;
  isEmpty: boolean;
}) {
  if (resource.loading)
    return (
      <div className="resource-state" role="status">
        <LoaderCircle className="spin" size={20} />
        正在加载…
      </div>
    );
  if (resource.error)
    return (
      <div className="resource-state error">
        <p role="alert">
          <AlertCircle size={18} />
          {resource.error}
        </p>
        <button className="button secondary" onClick={resource.retry}>
          <RotateCcw size={15} />
          重试
        </button>
      </div>
    );
  if (isEmpty)
    return (
      <div className="resource-state">
        <span className="empty-dot" />
        {empty}
      </div>
    );
  return null;
}
export function Section({
  id,
  title,
  english,
  children,
  aside,
}: {
  id: string;
  title: string;
  english: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section id={id} className="panel" aria-labelledby={`${id}-title`}>
      <header className="panel-header">
        <div>
          <p className="eyebrow">{english}</p>
          <h2 id={`${id}-title`}>{title}</h2>
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}
export function Modal({
  title,
  children,
  onClose,
  closeLabel = '关闭',
  busy = false,
  drawer = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  closeLabel?: string;
  busy?: boolean;
  drawer?: boolean;
}) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const shell = document.getElementById('console-shell');
    shell?.setAttribute('inert', '');
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyRef.current) {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key === 'Tab') {
        const items = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], summary, [tabindex="0"]',
          ) ?? [],
        );
        const first = items[0],
          last = items.at(-1);
        if (!first) {
          event.preventDefault();
          ref.current?.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      shell?.removeAttribute('inert');
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return createPortal(
    <div
      className={`modal-backdrop ${drawer ? 'drawer-backdrop' : ''}`}
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={ref}
        className={drawer ? 'drawer' : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
      >
        <header className="modal-header">
          <h2 id={id}>{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            disabled={busy}
            aria-label={closeLabel}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  );
}
