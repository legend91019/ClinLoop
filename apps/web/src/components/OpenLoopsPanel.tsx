import { ArrowUpRight } from 'lucide-react';
import type { LoopSummary } from '../api/types';
import type { Resource } from '../hooks/usePatientWorkflow';
import { Badge, formatTime, label, ResourceState, Section } from './shared';

export default function OpenLoopsPanel({
  resource,
  onTrace,
}: {
  resource: Resource<LoopSummary[]>;
  onTrace: (id: string) => void;
}) {
  const active =
    resource.data?.filter(
      (loop) => !['RESOLVED', 'CANCELLED'].includes(loop.state),
    ) ?? [];
  return (
    <Section
      id="loops"
      title="未闭环任务"
      english="OPEN LOOPS"
      aside={<span className="count">{active.length}</span>}
    >
      <ResourceState
        resource={resource}
        empty="暂无未闭环任务"
        isEmpty={!active.length}
      />
      <div className="loop-list">
        {!resource.loading &&
          !resource.error &&
          active.map((loop) => (
            <article className="loop-card" key={loop.loop_id}>
              <div className="card-top">
                <Badge value={loop.state} />
                <Badge value={loop.priority} />
              </div>
              <h3>{loop.goal}</h3>
              <dl className="compact-dl">
                <div>
                  <dt>等待</dt>
                  <dd>
                    {loop.waiting_for.length
                      ? loop.waiting_for.map(label).join('、')
                      : '未声明等待事件'}
                  </dd>
                </div>
                <div>
                  <dt>负责人</dt>
                  <dd>{loop.owner || '待分配'}</dd>
                </div>
                <div>
                  <dt>下次检查</dt>
                  <dd>
                    <time dateTime={loop.next_check_at ?? undefined}>
                      {formatTime(loop.next_check_at)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>依赖任务</dt>
                  <dd>{loop.depends_on.join('、') || '无'}</dd>
                </div>
              </dl>
              <footer>
                <span className="tiny-id">{loop.loop_id}</span>
                <button
                  className="text-button"
                  onClick={() => {
                    onTrace(loop.loop_id);
                    document.getElementById('trace')?.scrollIntoView?.({
                      behavior: 'smooth',
                      block: 'start',
                    });
                  }}
                >
                  查看轨迹
                  <ArrowUpRight size={15} />
                </button>
              </footer>
            </article>
          ))}
      </div>
    </Section>
  );
}
