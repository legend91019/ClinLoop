import { useState } from 'react';
import { Check, ExternalLink, X } from 'lucide-react';
import { isClinician } from '../api/client';
import type {
  Clinician,
  FindingResponse,
  ReviewAction,
  ReviewResponse,
} from '../api/types';
import type { Resource } from '../hooks/usePatientWorkflow';
import ReviewDialog from './ReviewDialog';
import { Badge, formatTime, label, ResourceState, Section } from './shared';

export default function WorkflowGapsPanel({
  resource,
  actor,
  onEvidence,
  onReviewed,
}: {
  resource: Resource<FindingResponse[]>;
  actor: Clinician | null;
  onEvidence: (id: string) => void;
  onReviewed: (response: ReviewResponse) => void;
}) {
  const [review, setReview] = useState<{
    finding: FindingResponse;
    action: ReviewAction;
  } | null>(null);
  const [notice, setNotice] = useState('');
  return (
    <>
      <Section
        id="gaps"
        title="流程缺口"
        english="WORKFLOW GAPS"
        aside={
          <span className="count amber-count">
            {resource.data?.filter(
              (item) => item.review_status === 'PENDING_REVIEW',
            ).length ?? 0}
          </span>
        }
      >
        <p className="panel-note">
          检索范围内未找到记录 ≠ 事实不存在。请核对证据后记录审核决定。
        </p>
        {notice && (
          <p className="success-text" role="status">
            {notice}
          </p>
        )}
        <ResourceState
          resource={resource}
          empty="暂无流程缺口"
          isEmpty={!resource.data?.length}
        />
        <div className="gap-list">
          {!resource.loading &&
            !resource.error &&
            resource.data?.map((finding) => (
              <article className="gap-card" key={finding.finding_id}>
                <div className="card-top">
                  <span className="gap-type" title={finding.finding_type}>
                    {label(finding.finding_type)}
                  </span>
                  <Badge value={finding.review_status} />
                </div>
                <p className="gap-claim">{finding.claim}</p>
                <dl className="compact-dl">
                  <div>
                    <dt>支持证据</dt>
                    <dd className="evidence-links">
                      {finding.supporting_evidence.length
                        ? finding.supporting_evidence.map((id) => (
                            <button
                              key={id}
                              className="evidence-link"
                              aria-label={`查看证据 ${id}`}
                              onClick={() => onEvidence(id)}
                            >
                              <ExternalLink size={13} />
                              {id}
                            </button>
                          ))
                        : '未提供证据'}
                    </dd>
                  </div>
                  <div>
                    <dt>检索来源</dt>
                    <dd className="searched-sources">
                      {finding.searched_sources.map((source) => (
                        <span key={source}>{source}</span>
                      ))}
                    </dd>
                  </div>
                  <div>
                    <dt>置信度</dt>
                    <dd>
                      {Math.round(finding.confidence * 100)}% · 检出于{' '}
                      {formatTime(finding.detected_at)}
                    </dd>
                  </div>
                </dl>
                <footer>
                  <span className="tiny-id">{finding.finding_id}</span>
                  {finding.review_status === 'PENDING_REVIEW' && (
                    <div className="actions">
                      <button
                        className="button small secondary"
                        disabled={!isClinician(actor)}
                        onClick={() => setReview({ finding, action: 'REJECT' })}
                      >
                        <X size={14} />
                        驳回
                      </button>
                      <button
                        className="button small primary"
                        disabled={!isClinician(actor)}
                        onClick={() => setReview({ finding, action: 'ACCEPT' })}
                      >
                        <Check size={14} />
                        接受
                      </button>
                    </div>
                  )}
                </footer>
              </article>
            ))}
        </div>
      </Section>
      {review && (
        <ReviewDialog
          finding={review.finding}
          action={review.action}
          actor={actor}
          onClose={() => setReview(null)}
          onReviewed={(response) => {
            onReviewed(response);
            setNotice('审核已记录 · 原始描述与证据已保留');
            setReview(null);
          }}
        />
      )}
    </>
  );
}
