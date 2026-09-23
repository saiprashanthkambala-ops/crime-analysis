import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useI18n } from '../i18n'
import { Spinner, ErrorBox, Panel, KV } from '../components/ui'

const STAGE_LABELS = {
  queued: 'Queued', uploaded: 'Uploaded', validating: 'Validating',
  parsing: 'Parsing', ocr_processing: 'OCR', extracting: 'Extracting',
  normalizing: 'Normalizing', resolving: 'Resolving', analyzing: 'Analyzing',
  completed: 'Completed', failed: 'Failed',
}

export default function CaseDetail() {
  const { caseId } = useParams()
  const { t } = useI18n()
  const [caseData, setCaseData] = useState(null)
  const [err, setErr] = useState('')

  const load = () => api(`/cases/${caseId}`).then(setCaseData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [caseId])

  if (err) return <ErrorBox message={err} />
  if (!caseData) return <Spinner />

  return (
    <div className="page case-detail-page">
      <Link className="btn btn-outline case-back-button" to="/cases" aria-label={t('cases_title')}>
        <span aria-hidden="true">←</span>
        {t('cases_title')}
      </Link>
      <div className="page-head">
        <div>
          <h2>{caseData.name}</h2>
          <p className="muted">{caseData.description}</p>
        </div>
        <Link className="btn btn-primary" to={`/cases/${caseId}/import`}>
          {t('import_dataset')}
        </Link>
      </div>
      <div className="kv-row">
        <KV k={t('case_id_label')} v={caseData.id} />
        <KV k={t('col_status')} v={caseData.status} />
        <KV k={t('created_label')} v={caseData.created_at ? new Date(caseData.created_at).toLocaleString() : null} />
      </div>

      <Panel title={t('documents_count_title', { count: caseData.documents.length })}
        actions={<Link className="link" to={`/cases/${caseId}/import`}>{t('import_view_full_history')}</Link>}>
        {caseData.documents.length === 0 && <div className="empty muted">{t('no_documents_uploaded')}</div>}
        <table className="table">
          <thead>
            <tr><th>{t('col_file')}</th><th>{t('col_type')}</th><th>{t('col_uploaded')}</th><th>{t('col_status')}</th></tr>
          </thead>
          <tbody>
            {caseData.documents.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.filename}</td>
                <td className="muted">{d.file_type || '—'}</td>
                <td className="muted small">
                  {d.created_at ? new Date(d.created_at).toLocaleString() : '—'}
                </td>
                <td>
                  <span className={`badge status-${d.status}`}>
                    {t('stage_' + d.status, null, STAGE_LABELS[d.status] || d.status)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div className="two-col">
        <Panel title={t('import_investigation_data')}>
          <p className="muted small">
            {t('import_inv_data_desc')}
          </p>
          <ul className="feature-list small">
            <li>{t('feature_multifile')}</li>
            <li>{t('feature_csv_mapping')}</li>
            <li>{t('feature_live_stages')}</li>
            <li>{t('feature_duplicate_detection')}</li>
          </ul>
          <Link className="btn btn-primary" to={`/cases/${caseId}/import`}>
            {t('open_dataset_importer')}
          </Link>
        </Panel>

        <Panel title={t('evidence_backed_by_design')}>
          <p className="muted small">
            {t('evidence_backed_desc')}
          </p>
          <div className="kv-row">
            <KV k={t('evidence_records_stat')} v={caseData.documents.length} />
          </div>
          <p className="muted small">
            {t('pipeline_explore_desc')}
          </p>
          <div className="quick-actions">
            <Link className="btn btn-outline" to={`/graph?case=${caseId}`}>{t('nav_network')}</Link>
            <Link className="btn btn-outline" to={`/timeline?case=${caseId}`}>{t('nav_timeline')}</Link>
          </div>
        </Panel>
      </div>
    </div>
  )
}

