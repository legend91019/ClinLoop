import type { TimelineResponse } from '../api/types';
import type { Resource } from '../hooks/usePatientWorkflow';
import { formatTime, label, ResourceState, Section } from './shared';

export default function PatientTimeline({
  resource,
  hours,
  setHours,
}: {
  resource: Resource<TimelineResponse>;
  hours: number;
  setHours: (hours: number) => void;
}) {
  return (
    <Section
      id="timeline"
      title="患者时间线"
      english="PATIENT TIMELINE"
      aside={
        <label className="inline-label">
          时间范围
          <select
            aria-label="时间范围"
            value={hours}
            onChange={(event) => setHours(Number(event.target.value))}
          >
            <option value={24}>最近 24 小时</option>
            <option value={72}>最近 72 小时</option>
            <option value={720}>最近 720 小时（30 天）</option>
          </select>
        </label>
      }
    >
      <p className="panel-note">
        按事件发生时间排列 · 所有显示时间为北京时间 UTC+8
      </p>
      <ResourceState
        resource={resource}
        empty="此时间范围内暂无事件"
        isEmpty={!resource.data?.entries.length}
      />
      {!resource.loading && !resource.error && resource.data && (
        <ol className="timeline">
          {resource.data.entries.map((entry) => (
            <li key={entry.event_id}>
              <time dateTime={entry.event_time}>
                {formatTime(entry.event_time)}
              </time>
              <div className="timeline-record">
                <span className="timeline-node" />
                <h3>{label(entry.event_type)}</h3>
                <p className="source-ref">{entry.payload_ref}</p>
                <p className="meta">
                  <span>
                    {entry.actor.display_name || entry.actor.actor_id}
                  </span>
                  <span>{entry.actor.role}</span>
                  <span title={entry.source_time}>
                    来源记录时间 {formatTime(entry.source_time)}
                  </span>
                </p>
                <span className="tiny-id">{entry.event_id}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
