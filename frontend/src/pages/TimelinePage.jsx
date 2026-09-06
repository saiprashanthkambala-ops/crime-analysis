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
  const [err, setErr] = useState('')

  useEffect(() => { api('/timeline').then(setItems).catch((e) => setErr(e.message)) }, [])

  if (err) return <ErrorBox message={err} />
  if (!items) return <Spinner />

  return (
    <div className="page">
      <h2>Timeline</h2>
      <p className="muted">Chronological events using only known dates/times. Missing times are never invented.</p>
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
