import { useCallback } from 'react';
import { api } from '../api/client';
import type { LoopSummary, ToolCall } from '../api/types';
import { useResource, type Resource } from '../hooks/usePatientWorkflow';
import { Badge, formatTime, ResourceState, Section } from './shared';

function Tool({ tool }: { tool: ToolCall }) {
  return (
    <div className="trace-tool">
      <p>
        <code>{tool.tool_name}</code>
        <span className={tool.ok ? 'tool-ok' : 'error-text'}>
          {tool.ok ? '成功' : `失败 · ${tool.error_code || '未知错误'}`}
        </span>
        {tool.duration_ms !== null && <span>{tool.duration_ms} ms</span>}
      </p>
      <p className="meta">
        工具输出引用：{tool.result_ref || '未提供'} ·{' '}
        {formatTime(tool.started_at)}
      </p>
      <details>
        <summary>ACT 参数</summary>
        <pre className="raw-record">
          {JSON.stringify(tool.arguments, null, 2)}
        </pre>
      </details>
    </div>
  );
}
function TraceContent({ loopId }: { loopId: string }) {
  const resource = useResource(
    useCallback(
      async (signal: AbortSignal) => {
        const result = await api.getTrace(loopId, signal);
        if (result.some((run) => run.loop_id !== loopId))
          throw new Error('运行轨迹与所选任务不匹配');
        return result;
      },
      [loopId],
    ),
  );
  return (
    <>
      <ResourceState
        resource={resource}
        empty="此任务暂无运行轨迹"
        isEmpty={!resource.data?.length}
      />
      {resource.data?.map((run) => (
        <article className="trace-run" key={run.run_id}>
          <header>
            <span className="tiny-id">{run.run_id}</span>
            {run.stop_reason ? (
              <Badge value={run.stop_reason} />
            ) : (
              <Badge value="运行中" />
            )}
          </header>
          <p className="meta">
            触发事件 {run.trigger_event_id} · 意图 {run.intent_id || '未关联'}
          </p>
          {run.trace_metadata?.provider && (
            <div className="trace-model-meta">
              <strong>模型参与</strong>
              <span>
                {run.trace_metadata.provider} ·{' '}
                {run.trace_metadata.model || '未声明'}
              </span>
              {run.trace_metadata.proposal_ref && (
                <span>提案 {run.trace_metadata.proposal_ref}</span>
              )}
              {run.trace_metadata.error_code && (
                <span className="error-text">
                  错误 {run.trace_metadata.error_code}
                </span>
              )}
            </div>
          )}
          <ol className="trace-steps">
            {run.steps.map((step, index) => (
              <li key={step.step_id}>
                <span className="step-index">{index + 1}</span>
                <div>
                  <div className="card-top">
                    <strong>{step.kind}</strong>
                    <time
                      className="meta"
                      dateTime={step.started_at ?? undefined}
                    >
                      {formatTime(step.started_at)} →{' '}
                      {formatTime(step.finished_at)}
                    </time>
                  </div>
                  <p>{step.reason}</p>
                  <p className="meta">
                    输入引用：{step.input_ref || '未提供'} · 输出引用：
                    {step.output_ref || '未提供'}
                  </p>
                  {step.tool_call && <Tool tool={step.tool_call} />}
                </div>
              </li>
            ))}
          </ol>
          {run.tool_calls
            .filter(
              (tool) =>
                !run.steps.some(
                  (step) =>
                    step.tool_call?.tool_name === tool.tool_name &&
                    step.tool_call?.started_at === tool.started_at,
                ),
            )
            .map((tool, index) => (
              <Tool key={index} tool={tool} />
            ))}
        </article>
      ))}
    </>
  );
}
export default function AgentTracePanel({
  loops,
  selected,
  onSelect,
}: {
  loops: Resource<LoopSummary[]>;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const valid = loops.data?.some((loop) => loop.loop_id === selected);
  return (
    <Section
      id="trace"
      title="Agent 运行轨迹"
      english="AGENT TRACE"
      aside={
        loops.data?.length ? (
          <select
            aria-label="选择轨迹任务"
            value={selected}
            onChange={(event) => onSelect(event.target.value)}
          >
            {loops.data.map((loop) => (
              <option key={loop.loop_id} value={loop.loop_id}>
                {loop.loop_id} · {loop.goal}
              </option>
            ))}
          </select>
        ) : undefined
      }
    >
      <p className="panel-note">
        OBSERVE → REASON → PLAN → ACT → VERIFY · 工具参数按需展开
      </p>
      {loops.loading || loops.error || !loops.data?.length ? (
        <ResourceState
          resource={loops}
          empty="暂无可查看轨迹的任务"
          isEmpty={!loops.data?.length}
        />
      ) : valid ? (
        <TraceContent key={selected} loopId={selected} />
      ) : (
        <p className="resource-state">请选择任务查看轨迹</p>
      )}
    </Section>
  );
}
