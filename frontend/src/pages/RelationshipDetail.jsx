import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge, Empty } from '../components/ui'

export default function RelationshipDetail() {
  const { relId } = useParams()
  const [rel, setRel] = useState(null)
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  const load = () => api(`/relationships/${relId}`).then(setRel).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [relId])

  const decide = async (decision) => {
    setSaving(true)
    try {
      await api(`/relationships/${relId}/feedback`, {
        method: 'POST', body: JSON.stringify({ decision, note }),
      })
      setNote('')
      await load()
    } catch (e) { setErr(e.message) } finally { setSaving(false) }
  }

  if (err) return <ErrorBox message={err} />
  if (!rel) return <Spinner />

  const s = rel.signals

  return (
    <div className="page">
      <div className="rel-header">
        <div className="rel-person">
          <Link className="link" to={`/persons/${rel.person_a.id}`}>{rel.person_a.name}</Link>
        </div>
        <div className="rel-center">
          <div className="rel-link-symbol">↔</div>
          <StrengthBadge strength={rel.strength} />
          <div className="muted small">Evidence Strength · score {rel.score}</div>
        </div>
        <div className="rel-person">
          <Link className="link" to={`/persons/${rel.person_b.id}`}>{rel.person_b.name}</Link>
        </div>
      </div>

      <div className="two-col">
        <Panel title="Why this relationship was surfaced">
          <ul className="signal-list">
            {s.calls > 0 && <li><span className="sig-count">{s.calls}</span> call interactions</li>}
            {s.transactions > 0 && <li><span className="sig-count">{s.transactions}</span> transaction interactions</li>}
            {s.location_overlaps > 0 && <li><span className="sig-count">{s.location_overlaps}</span> location overlaps / co-observations</li>}
            {s.shared_identifiers?.length > 0 && (
              <li>Shared identifiers: {s.shared_identifiers.join(', ')}</li>
            )}
            {s.case_overlaps > 0 && <li><span className="sig-count">{s.case_overlaps}</span> shared cases</li>}
            {s.calls + s.transactions + s.location_overlaps + (s.shared_identifiers?.length || 0) + s.case_overlaps === 0 && (
              <li className="muted">No supporting signals.</li>
            )}
          </ul>
        </Panel>

        <Panel title="Uncertainties">
          <ul className="signal-list muted">
            <li>Signals from {rel.sources.length} distinct source(s).</li>
            <li>Identifier ownership may not be independently verified.</li>
            <li>Co-location alone is not treated as decisive evidence.</li>
          </ul>
        </Panel>
      </div>

      <Panel title="Sources">
        {rel.sources.length === 0 && <Empty message="No source records." />}
        <div className="source-list">
          {rel.sources.map((src) => <div key={src} className="source-chip mono">{src}</div>)}
        </div>
      </Panel>

      <Panel title="Temporal Context">
        {rel.dates.length === 0
          ? <Empty message="No known dates." />
          : <div className="mono">{rel.dates.join('  →  ')}</div>}
      </Panel>

      <Panel title="Supporting Evidence">
        {rel.evidence.length === 0 && <Empty message="No evidence records." />}
        <table className="table">
          <thead><tr><th>ID</th><th>Type</th><th>Source</th><th>Date</th><th>Time</th></tr></thead>
          <tbody>
            {rel.evidence.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.id}</td>
                <td className="muted">{e.type}</td>
                <td className="mono">{e.source}</td>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">Unavailable</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Investigator Decision">
        <div className="decision-row">
          <button className="btn btn-ok" disabled={saving} onClick={() => decide('relevant')}>✓ Relevant</button>
          <button className="btn btn-bad" disabled={saving} onClick={() => decide('incorrect')}>✕ Incorrect</button>
          <button className="btn btn-warn" disabled={saving} onClick={() => decide('needs_review')}>? Needs Review</button>
          {rel.decision && <span className="muted">Current decision: <b>{rel.decision.replace('_', ' ')}</b></span>}
        </div>
        <textarea
          placeholder="Optional note for this decision…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          style={{ marginBottom: 8 }}
        />
        <div className="small muted">Feedback is stored for controlled evaluation — not unsupervised model change.</div>
      </Panel>
    </div>
  )
}
