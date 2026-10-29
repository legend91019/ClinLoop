import { useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { api } from '../api/client';
import type { Clinician } from '../api/types';
import type {
  ClinicalDocument,
  DocumentKind,
  DraftMode,
  Interview,
  PatientProfile,
} from '../api/workspaceTypes';
import { formatTime } from './shared';

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

function draftingFailure(code?: string) {
  const messages: Record<string, string> = {
    NOTE_DRAFT_NOT_CONFIGURED:
      '尚未连接真实病历撰写模型，请配置后重启服务，再从历史对话重新撰写。',
    NOTE_DRAFT_AUTH_ERROR: '病历撰写服务认证失败，请检查模型密钥及账号权限。',
    NOTE_DRAFT_MODEL_UNAVAILABLE: '当前模型或服务地址不可用，请检查模型配置。',
    NOTE_DRAFT_RATE_LIMITED: '模型服务请求受限，请稍后重试并检查账号额度。',
    NOTE_DRAFT_TIMEOUT: '模型撰写超时，请稍后从历史对话重试。',
    NOTE_DRAFT_CONNECTION_ERROR: '无法连接病历撰写模型，请检查网络后重试。',
    NOTE_DRAFT_UNSUPPORTED_CLINICAL_PLAN:
      '诊疗评估或计划缺少可核对的医生发言来源，未保存草稿。请核对说话人标记，或重试撰写。',
  };
  return `原始对话已保存。${messages[code || ''] || `病历撰写未完成（${code || '未知错误'}），可从原文重新撰写。`}`;
}

export default function InterviewComposer({
  profile,
  actor,
  active,
  onReady,
  onDirtyChange,
}: {
  profile: PatientProfile;
  actor: Clinician | null;
  active: boolean;
  onReady: (document: ClinicalDocument) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const storageKey = `clinloop:interview:${profile.patient_id}:${profile.encounter_id}`;
  const [text, setText] = useState(() => {
    try {
      return sessionStorage.getItem(storageKey) || '';
    } catch {
      return '';
    }
  });
  const [kind, setKind] = useState<DocumentKind>('ROUND');
  const [draftMode, setDraftMode] = useState<DraftMode>('CLINICAL');
  const [config, setConfig] = useState<{
    configured: boolean;
    model: string;
  } | null>(null);
  const [configError, setConfigError] = useState('');
  const [interim, setInterim] = useState('');
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<Interview[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const recognition = useRef<Recognition | null>(null);
  const request = useRef<{
    id: string;
    text: string;
    kind: DocumentKind;
    mode: DraftMode;
  } | null>(null);
  const alive = useRef(true);
  const ready = useRef(onReady);
  ready.current = onReady;
  const watched = useRef<string | null>(null);
  const redraftRequest = useRef<{
    interview: string;
    mode: DraftMode;
    id: string;
  } | null>(null);
  const Speech =
    (window as SpeechWindow).SpeechRecognition ||
    (window as SpeechWindow).webkitSpeechRecognition;
  useEffect(() => {
    const controller = new AbortController();
    api
      .clinicalWritingConfig(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setConfig(value);
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setConfigError(e.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    try {
      if (text) sessionStorage.setItem(storageKey, text);
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* In-memory editing remains available. */
    }
    onDirtyChange(!!text.trim());
  }, [text, storageKey, onDirtyChange]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      recognition.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!active) recognition.current?.stop();
  }, [active]);
  useEffect(() => {
    const stop = () => {
      if (document.hidden) recognition.current?.stop();
    };
    document.addEventListener('visibilitychange', stop);
    return () => document.removeEventListener('visibilitychange', stop);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      void api
        .listInterviews(
          profile.patient_id,
          profile.encounter_id,
          controller.signal,
        )
        .then((items) => {
          if (controller.signal.aborted) return;
          setRows(items);
          const completed = items.find(
            (item) =>
              item.interview_id === watched.current &&
              item.generation.status !== 'QUEUED',
          );
          if (completed) {
            watched.current = null;
            if (completed.document) {
              ready.current(completed.document);
              setMessage('Agent 草稿已生成，请核对原文、检查记录并签署。');
            } else setError(draftingFailure(completed.generation.error));
          }
        })
        .catch((e: Error) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    load();
    const timer = window.setInterval(load, 3000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [profile.patient_id, profile.encounter_id]);
  function start() {
    if (!Speech || recognition.current || busy) return;
    setError('');
    const instance = new Speech();
    recognition.current = instance;
    instance.lang = 'zh-CN';
    instance.continuous = true;
    instance.interimResults = true;
    instance.onresult = (event) => {
      if (!alive.current) return;
      let final = '';
      let pending = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const item = event.results[i];
        if (item.isFinal) final += item[0].transcript + '\n';
        else pending += item[0].transcript;
      }
      if (final)
        setText(
          (previous) =>
            (previous ? previous.replace(/\s+$/, '') + '\n' : '') +
            final.trim(),
        );
      setInterim(pending);
    };
    instance.onerror = (event) => {
      if (alive.current)
        setError(
          `语音识别未能继续（${event.error}）。已转录文字会保留，可重新开始或手动补录。`,
        );
    };
    instance.onend = () => {
      recognition.current = null;
      if (alive.current) {
        setListening(false);
        setInterim('');
      }
    };
    try {
      instance.start();
      setListening(true);
    } catch {
      recognition.current = null;
      setError('无法启动麦克风，请检查浏览器权限，或手动录入对话。');
    }
  }
  async function save() {
    if (!actor) {
      setError('请先在上方填写医生 ID 并选择临床角色，再保存问诊。');
      document.getElementById('actor-id')?.focus();
      return;
    }
    setBusy(true);
    setError('');
    if (
      !request.current ||
      request.current.text !== text.trim() ||
      request.current.kind !== kind ||
      request.current.mode !== draftMode
    )
      request.current = {
        id: crypto.randomUUID(),
        text: text.trim(),
        kind,
        mode: draftMode,
      };
    try {
      const result = await api.saveInterview(
        profile.patient_id,
        {
          encounter_id: profile.encounter_id,
          request_id: request.current.id,
          transcript: request.current.text,
          kind,
          draft_mode: draftMode,
        },
        actor,
      );
      if (!alive.current) return;
      setRows((items) => [
        result,
        ...items.filter((item) => item.interview_id !== result.interview_id),
      ]);
      setText('');
      request.current = null;
      if (result.document) ready.current(result.document);
      else watched.current = result.interview_id;
      setMessage(
        '原始对话已保存，Agent 正在起草。无需重复提交，可稍后从历史记录打开。',
      );
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function retry(item: Interview) {
    if (!actor) {
      setError('请先填写医生身份。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (
        !redraftRequest.current ||
        redraftRequest.current.interview !== item.interview_id ||
        redraftRequest.current.mode !== draftMode
      )
        redraftRequest.current = {
          interview: item.interview_id,
          mode: draftMode,
          id: crypto.randomUUID(),
        };
      await api.redraftInterview(
        profile.patient_id,
        item.interview_id,
        { request_id: redraftRequest.current.id, draft_mode: draftMode },
        actor,
      );
      redraftRequest.current = null;
      watched.current = item.interview_id;
      setRows((items) =>
        items.map((row) =>
          row.interview_id === item.interview_id
            ? { ...row, generation: { status: 'QUEUED' } }
            : row,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="interview-composer" aria-label="问诊与查房转录">
      <h3>问诊与查房 · 原始对话</h3>
      <p>
        保存原始对话后，Agent
        综合患者资料、既往文书及已有检查，另外撰写连贯的临床文书。原文与撰写依据单独保留，正文由医生审核签署。
      </p>
      <p className="panel-note">
        可在对话中标注“医生：”“患者：”，帮助区分提问、患者陈述与医生安排。
      </p>
      {config && (
        <p className={config.configured ? 'workspace-success' : 'panel-note'}>
          {config.configured
            ? `病历撰写模型已配置：${config.model}（是否可用以实际请求结果为准）`
            : '尚未配置真实病历撰写模型。可先保存对话，配置并重启后重新撰写；也可选择本地格式演示查看文书结构。'}
        </p>
      )}
      {configError && (
        <p className="panel-note">暂时无法读取模型连接状态：{configError}</p>
      )}
      <div className="workspace-actions">
        <label>
          撰写方式
          <select
            aria-label="撰写方式"
            value={draftMode}
            disabled={busy || listening}
            onChange={(e) => setDraftMode(e.target.value as DraftMode)}
          >
            <option value="CLINICAL">正式病历草稿（真实模型）</option>
            <option value="DEMO">文书格式演示（本地模板）</option>
          </select>
        </label>
        <label>
          生成记录类型
          <select
            value={kind}
            disabled={busy || listening}
            onChange={(e) => setKind(e.target.value as DocumentKind)}
          >
            <option value="ROUND">查房记录</option>
            <option value="ADMISSION">入院病历</option>
            <option value="PROGRESS">病程记录</option>
          </select>
        </label>
        <button
          type="button"
          className="button"
          disabled={!Speech || busy || listening}
          onClick={start}
        >
          <Mic size={16} />
          开始语音转录
        </button>
        <button
          type="button"
          className="button"
          disabled={!listening}
          onClick={() => recognition.current?.stop()}
        >
          <Square size={16} />
          停止转录
        </button>
      </div>
      {draftMode === 'DEMO' && (
        <p className="panel-note">
          当前为格式演示：只展示模板及有限口语改写，未调用模型，不代表真实临床撰写效果。
        </p>
      )}
      <p className="panel-note">
        {Speech
          ? '语音识别由当前浏览器提供，可能需要联网及麦克风权限；服务不可用时请手动输入。'
          : '当前浏览器不支持语音识别，请手动输入或粘贴转录文字。'}
        仅保存文字，未保存音频。
      </p>
      <label>
        医患原始对话
        <textarea
          rows={8}
          maxLength={25000}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            '医生：今天有哪些不适？\n患者：……\n医生：复查血常规，结果出来后提醒我查看。'
          }
        />
      </label>
      {listening && <p role="status">正在转录… {interim}</p>}
      <button
        type="button"
        className="button primary"
        disabled={
          busy || listening || text.trim().length < 5 || text.length > 25000
        }
        onClick={() => void save()}
      >
        {busy ? '保存中…' : '保存对话并生成病历'}
      </button>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="workspace-success">
          {message}
        </p>
      )}
      {rows[0] && (
        <div
          aria-label="最近病历生成状态"
          className={
            rows[0].generation.status === 'FAILED'
              ? 'error-text'
              : 'workspace-success'
          }
        >
          {rows[0].generation.status === 'FAILED' ? (
            <>
              <strong>最近一次病历未生成</strong>
              <p>{draftingFailure(rows[0].generation.error)}</p>
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void retry(rows[0])}
              >
                重新撰写最近一次病历
              </button>
            </>
          ) : rows[0].document ? (
            <>
              <strong>最近一次病历已生成：{rows[0].document.title}</strong>
              <button
                type="button"
                className="button"
                onClick={() => ready.current(rows[0].document!)}
              >
                打开最新病历
              </button>
            </>
          ) : (
            <p>最近一次病历正在撰写，请稍候。生成后可在此直接打开。</p>
          )}
        </div>
      )}
      <details>
        <summary>已保存的原始对话（{rows.length}）</summary>
        {rows.map((item) => (
          <article key={item.interview_id} className="interview-history">
            <strong>
              {formatTime(item.saved_at)} ·{' '}
              {item.kind === 'ROUND' ? '查房' : '问诊'}
            </strong>
            <pre>{item.transcript}</pre>
            {item.document ? (
              <button
                type="button"
                className="button"
                onClick={() => ready.current(item.document!)}
              >
                打开病历
                {item.document.status === 'SUBMITTED' ? '（已签署）' : '草稿'}
              </button>
            ) : item.generation.status === 'FAILED' ? (
              <>
                <p className="error-text">
                  {draftingFailure(item.generation.error)}
                </p>
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  onClick={() => void retry(item)}
                >
                  重新撰写病历
                </button>
              </>
            ) : (
              <p>Agent 正在排队起草…</p>
            )}
            {item.generation.status === 'READY' && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void retry(item)}
              >
                根据原文重新撰写新版本
              </button>
            )}
          </article>
        ))}
      </details>
    </section>
  );
}
