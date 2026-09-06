import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge } from '../components/ui'

const FILTERS = ['', 'STRONG', 'MODERATE', 'WEAK', 'INSUFFICIENT EVIDENCE']
const SIGNALS = [
  { value: '', label: 'All types' },
  { value: 'call', label: 'Calls' },
  { value: 'transaction', label: 'Transactions' },
  { value: 'location', label: 'Location' },
  { value: 'shared_identifier', label: 'Shared identifier' },
  { value: 'case', label: 'Shared case' },
]

export default function Relationships() {
  const [rels, setRels] = useState(null)
  const [cases, setCases] = useState([])
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')
  const [signal, setSignal] = useState('')
  const [caseId, setCaseId] = useState('')

  useEffect(() => {
    api('/relationships').then(setRels).catch((e) => setErr(e.message))
    api('/cases').then(setCases).catch(() => {})
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!rels) return <Spinner />

  const shown = rels.filter((r) => {
    if (filter && r.strength !== filter) return false
    if (signal && !(r.types || []).includes(signal)) return false
    if (caseId && !(r.case_ids || []).includes(caseId)) return false
    return true
  })

  return (
    <div className="page">
      <h2>Relationships</h2>
      <p className="muted">
        Candidate relationships. Strength reflects the weight of supporting evidence — not guilt probability.
      </p>

      <div className="filter-row">
        {FILTERS.map((f) => (
          <button
            key={f || 'all'}
            className={`btn ${filter === f ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setFilter(f)}
          >
            {f || 'All'}
          </button>
        ))}
        <select value={signal} onChange={(e) => setSignal(e.target.value)} className="select-inline">
          {SIGNALS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={caseId} onChange={(e) => setCaseId(e.target.value)} className="select-inline">
          <option value="">All cases</option>
          {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <Panel title={`${shown.length} relationships`}>
        <table className="table">
          <thead>
            <tr><th>Person A</th><th>Person B</th><th>Strength</th><th>Score</th><th>Signals</th><th>Decision</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id}>
                <td><Link className="link" to={`/persons/${r.person_a.id}`}>{r.person_a.name}</Link></td>
                <td><Link className="link" to={`/persons/${r.person_b.id}`}>{r.person_b.name}</Link></td>
                <td><StrengthBadge strength={r.strength} /></td>
                <td className="mono">{r.score}</td>
                <td className="muted">
                  {r.signals.calls}c · {r.signals.transactions}t · {r.signals.location_overlaps}l
                </td>
                <td>{r.decision ? <span className="badge decision-badge">{r.decision}</span> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
