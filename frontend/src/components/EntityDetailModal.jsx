import { useI18n } from '../i18n'

function Value({ value }) {
  if (value === null || value === undefined || value === '') return <span className="muted">—</span>
  if (typeof value === 'object') return <span className="mono">{JSON.stringify(value)}</span>
  return <span>{String(value)}</span>
}

export default function EntityDetailModal({ node, detail, loading, onClose }) {
  const { t } = useI18n()

  return (
    <div className="entity-modal-backdrop" role="presentation" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose()
    }}>
      <section className="entity-modal" role="dialog" aria-modal="true" aria-labelledby="entity-modal-title">
        <div className="entity-modal-head">
          <div>
            <span className="entity-modal-kicker">{t('entity_details')}</span>
            <h3 id="entity-modal-title">{detail?.display_name || node?.label || node?.id || t('entity_details')}</h3>
          </div>
          <button type="button" className="entity-modal-close" onClick={onClose} aria-label={t('close')}>×</button>
        </div>

        {loading ? (
          <div className="entity-modal-loading">{t('loading_entity_details')}</div>
        ) : detail ? (
          <div className="entity-modal-grid">
            <div className="entity-modal-section">
              <h4>{t('entity_information')}</h4>
              <div className="entity-detail-list">
                <div><span>{t('entity_type')}</span><strong><Value value={detail.entity_type || detail.node_type} /></strong></div>
                <div><span>{t('entity_value')}</span><strong><Value value={detail.value || detail.display_name} /></strong></div>
                <div><span>{t('normalized_value')}</span><strong><Value value={detail.normalized_value} /></strong></div>
                <div><span>{t('entity_case')}</span><strong><Value value={detail.case?.name || detail.case?.id} /></strong></div>
                <div><span>{t('entity_case_id')}</span><strong className="mono"><Value value={detail.case?.id} /></strong></div>
                <div><span>{t('confidence')}</span><strong><Value value={detail.confidence} /></strong></div>
                <div><span>{t('observed_at')}</span><strong><Value value={detail.observed_at} /></strong></div>
              </div>

              {detail.related_people?.length > 0 && (
                <>
                  <h4>{t('related_people')}</h4>
                  <div className="entity-related-list">
                    {detail.related_people.map((person) => (
                      <div className="entity-related-item" key={person.id}>
                        <strong>{person.name || person.id}</strong>
                        <span className="muted mono">{person.id}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div className="entity-modal-section entity-source-section">
              <h4>{t('source_file')}</h4>
              {detail.source_files?.length ? (
                detail.source_files.map((file) => (
                  <div className="entity-source-card" key={file.id}>
                    <div className="entity-source-title">
                      <strong>{file.filename || file.id}</strong>
                      <span className="badge status-badge">{file.file_type || t('file')}</span>
                    </div>
                    <div className="entity-detail-list">
                      <div><span>{t('file_status')}</span><strong><Value value={file.status} /></strong></div>
                      <div><span>{t('file_records')}</span><strong><Value value={file.records_processed} /></strong></div>
                      <div><span>{t('file_created')}</span><strong><Value value={file.created_at} /></strong></div>
                    </div>
                    {file.source_preview ? (
                      <div className="entity-source-preview">
                        <div className="entity-source-preview-label">{t('file_review')}</div>
                        <pre>{file.source_preview}</pre>
                      </div>
                    ) : (
                      <div className="empty muted">{t('file_review_unavailable')}</div>
                    )}
                  </div>
                ))
              ) : (
                <div className="empty muted">{t('no_source_file')}</div>
              )}
            </div>
          </div>
        ) : (
          <div className="empty muted">{t('entity_details_unavailable')}</div>
        )}
      </section>
    </div>
  )
}
