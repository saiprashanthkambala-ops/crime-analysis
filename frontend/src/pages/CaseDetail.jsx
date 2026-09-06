import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, KV } from '../components/ui'

const STAGE_LABELS = {
  queued: 'Queued', uploaded: 'Uploaded', validating: 'Validating',
  parsing: 'Parsing', ocr_processing: 'OCR', extracting: 'Extracting',
  normalizing: 'Normalizing', resolving: 'Resolving', analyzing: 'Analyzing',
  completed: 'Completed', failed: 'Failed',
}

export default function CaseDetail() {
  const { caseId } = useParams()
  const [caseData, setCaseData] = useState(null)
  const [err, setErr] = useState('')

  const load = () => api(`/cases/${caseId}`).then(setCaseData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [caseId])

  if (err) return <ErrorBox message={err} />
  if (!caseData) return <Spinner />

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{caseData.name}</h2>
          <p className="muted">{caseData.description}</p>
        </div>
        <Link className="btn btn-primary" to={`/cases/${caseId}/import`}>
          ⬆ Import Dataset
        </Link>
      </div>
      <div className="kv-row">
        <KV k="Case ID" v={caseData.id} />
        <KV k="Status" v={caseData.status} />
        <KV k="Created" v={caseData.created_at ? new Date(caseData.created_at).toLocaleString() : null} />
      </div>

      <Panel title={`Documents (${caseData.documents.length})`}
        actions={<Link className="link" to={`/cases/${caseId}/import`}>Import / view full history →</Link>}>
        {caseData.documents.length === 0 && <div className="empty muted">No documents uploaded.</div>}
        <table className="table">
          <thead>
            <tr><th>File</th><th>Type</th><th>Uploaded</th><th>Status</th></tr>
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
                    {STAGE_LABELS[d.status] || d.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div className="two-col">
        <Panel title="Import investigation data">
          <p className="muted small">
            Use the dataset importer to upload PDF (text or scanned/OCR), CSV,
            JSON and TXT files. Files are validated before they touch the case,
            duplicate content is detected, and every record stays traceable to
            its source document through the CrimeLink pipeline.
          </p>
          <ul className="feature-list small">
            <li>Multi-file drag &amp; drop with per-file validation</li>
            <li>CSV column mapping to CrimeLink fields (auto-detect available)</li>
            <li>Live processing stages: validating → parsing/OCR → extracting →
              normalizing → resolving → analyzing</li>
            <li>Duplicate detection by content hash and one-click retry of failures</li>
          </ul>
          <Link className="btn btn-primary" to={`/cases/${caseId}/import`}>
            Open Dataset Importer →
          </Link>
        </Panel>

        <Panel title="Evidence-backed by design">
          <p className="muted small">
            Imported information is treated as <em>evidence to be validated</em>,
            never as automatically true. Original values are preserved alongside
            normalized values, and each entity / event / relationship links back
            to its source document — so an investigator always knows <em>why</em>.
          </p>
          <div className="kv-row">
            <KV k="Evidence records" v={caseData.documents.length} />
          </div>
          <p className="muted small">
            Explore what the pipeline discovered for this case from the network
            graph, timeline and evidence views.
          </p>
          <div className="quick-actions">
            <Link className="btn btn-outline" to={`/graph?case=${caseId}`}>Network</Link>
            <Link className="btn btn-outline" to={`/timeline?case=${caseId}`}>Timeline</Link>
          </div>
        </Panel>
      </div>
    </div>
  )
}
