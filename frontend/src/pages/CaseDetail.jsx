import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, uploadFile } from '../api'
import { Spinner, ErrorBox, Panel, KV } from '../components/ui'

export default function CaseDetail() {
  const { caseId } = useParams()
  const [caseData, setCaseData] = useState(null)
  const [err, setErr] = useState('')
  const [uploading, setUploading] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const fileRef = useRef(null)

  const load = () => api(`/cases/${caseId}`).then(setCaseData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [caseId])

  const onUpload = async (e) => {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setUploading(true)
    setStatusMsg('')
    try {
      const res = await uploadFile(caseId, file)
      setStatusMsg(`Uploaded ${res.filename} — status: ${res.status}`)
      await load()
    } catch (err) { setErr(err.message) } finally { setUploading(false) }
  }

  if (err) return <ErrorBox message={err} />
  if (!caseData) return <Spinner />

  return (
    <div className="page">
      <h2>{caseData.name}</h2>
      <p className="muted">{caseData.description}</p>
      <div className="kv-row">
        <KV k="Case ID" v={caseData.id} />
        <KV k="Status" v={caseData.status} />
        <KV k="Created" v={caseData.created_at ? new Date(caseData.created_at).toLocaleString() : null} />
      </div>

      <div className="two-col">
        <Panel title="Documents">
          {caseData.documents.length === 0 && <div className="empty muted">No documents uploaded.</div>}
          <table className="table">
            <tbody>
              {caseData.documents.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.filename}</td>
                  <td className="muted">{d.file_type}</td>
                  <td><span className={`badge status-${d.status}`}>{d.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Upload Investigation Data">
          <form onSubmit={onUpload} className="form">
            <label>File (PDF / CSV / JSON / TXT)</label>
            <input type="file" ref={fileRef} accept=".pdf,.csv,.json,.txt" />
            <button className="btn btn-primary" disabled={uploading}>
              {uploading ? 'Uploading & processing…' : 'Upload & Process'}
            </button>
            {statusMsg && <div className="info-box">{statusMsg}</div>}
            <div className="muted small">
              Processing pipeline: parse → extract → normalize → resolve → profile → relationships → evidence.
            </div>
          </form>
        </Panel>
      </div>
    </div>
  )
}
