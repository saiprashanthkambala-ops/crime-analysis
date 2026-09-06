import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'

const TYPE_COLORS = {
  CALL: '#38bdf8',
  TRANSACTION: '#f59e0b',
  LOCATION_OBSERVATION: '#fb7185',
  CASE_EVENT: '#94a3b8',
}

export default function TimelinePage() {
  const [items, setItems] = useState(null)
  const [cases, setCases] = useState([])
  const [err, setErr] = useState('')
  const [caseId, setCaseId] = useState('')
  const [eventType, setEventType] = useState('')

  useEffect(() => {
    const params = new URLSearchParams()
    if (caseId) params.set('case_id', caseId)
    if (eventType) params.set('event_type', eventType)
    const qs = params.toString()
    api(`/timeline${qs ? `?${qs}` : ''}`).then(setItems).catch((e) => setErr(e.message))
  }, [caseId, eventType])

  useEffect(() => { api('/cases').then(setCases).catch(() => {}) }, [])

  if (err) return <ErrorBox message={err} />
  if (!items) return <Spinner />

  return (
    <div className="page">
      <h2>Timeline</h2>
      <p className="muted">Chronological events using only known dates/times. Missing times are never invented.</p>
      <div className="filter-row">
        <select value={caseId} onChange={(e) => setCaseId(e.target.value)} className="select-inline">
          <option value="">All cases</option>
          {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={eventType} onChange={(e) => setEventType(e.target.value)} className="select-inline">
          <option value="">All event types</option>
          <option value="CALL">CALL</option>
          <option value="TRANSACTION">TRANSACTION</option>
          <option value="LOCATION_OBSERVATION">LOCATION_OBSERVATION</option>
          <option value="CASE_EVENT">CASE_EVENT</option>
        </select>
      </div>
      <Panel title={`${items.length} events`}>
        {items.length === 0 && <Empty message="No timeline events available." />}
        <div className="timeline">
          {items.map((e) => (
            <div key={e.id} className="timeline-item">
              <div className="timeline-marker" style={{ background: TYPE_COLORS[e.type] || '#94a3b8' }} />
              <div className="timeline-time">
                <div className="mono">{e.date}</div>
                <div className="mono">{e.time || <span className="muted">Time unavailable</span>}</div>
              </div>
              <div className="timeline-body">
                <span className="badge type-badge">{e.type}</span>
                <div className="muted">{e.description}</div>
                <div className="small muted mono">source: {e.source}</div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
