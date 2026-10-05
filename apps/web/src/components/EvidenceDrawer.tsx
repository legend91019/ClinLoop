import { useCallback } from 'react';
import { api } from '../api/client';
import { useResource } from '../hooks/usePatientWorkflow';
import { Badge, formatTime, Modal, ResourceState } from './shared';

export default function EvidenceDrawer({
  id,
  patient,
  onClose,
  onEncounter,
}: {
  id: string;
  patient: string;
  onClose: () => void;
  onEncounter: (id: string) => void;
}) {
  const resource = useResource(
    useCallback(
      async (signal: AbortSignal) => {
        const [evidence, source] = await Promise.all([
          api.getEvidence(id, signal),
          api.getEvidenceSource(id, signal),
        ]);
        if (source.patient_id !== patient)
          throw new Error('来源记录与当前患者不匹配，已阻止展示');
        if (
          evidence.evidence_id !== id ||
          (source.payload_ref !== evidence.source_id &&
            source.event_id !== evidence.source_id)
        )
          throw new Error('来源记录与证据引用不匹配，已阻止展示');
        return { evidence, source };
      },
      [id, patient],
    ),
  );
  const result = resource.data;
  return (
    <Modal
      title="证据与原始记录"
      onClose={onClose}
      closeLabel="关闭证据"
      drawer
    >
      <div className="modal-content">
        <p className="eyebrow">EVIDENCE / {id}</p>
        <ResourceState
          resource={resource}
          empty="暂无原始记录"
          isEmpty={!result}
        />
        {result && (
          <>
            <Badge value={result.evidence.trust_level} />
            <h3 className="drawer-claim">{result.evidence.claim}</h3>
            {result.evidence.trust_level === 'PATIENT_REPORTED' && (
              <p className="warning-note">
                患者自述需医生核验；不等同于系统验证证据。
              </p>
            )}
            <dl className="compact-dl">
              <div>
                <dt>来源类型</dt>
                <dd>{result.evidence.source_type}</dd>
              </div>
              <div>
                <dt>原始记录</dt>
                <dd>{result.evidence.source_id}</dd>
              </div>
              <div>
                <dt>观察时间</dt>
                <dd>{formatTime(result.evidence.observed_at)}</dd>
              </div>
              <div>
                <dt>患者</dt>
                <dd>{result.source.patient_id}</dd>
              </div>
              <div>
                <dt>就诊</dt>
                <dd>{result.source.encounter_id}</dd>
              </div>
              <div>
                <dt>记录人</dt>
                <dd>
                  {result.source.actor.display_name ||
                    result.source.actor.actor_id}
                </dd>
              </div>
            </dl>
            <button
              className="button secondary"
              onClick={() => onEncounter(result.source.encounter_id)}
            >
              选用此就诊 ID
            </button>
            <h3 className="raw-heading">原始 ClinicalEvent</h3>
            <p className="panel-note">
              以下为服务返回的完整原始记录，包含 payload、来源时间与记录人。
            </p>
            <pre className="raw-record" tabIndex={0}>
              {JSON.stringify(result.source, null, 2)}
            </pre>
          </>
        )}
      </div>
    </Modal>
  );
}
