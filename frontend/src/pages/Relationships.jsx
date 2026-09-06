import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge } from '../components/ui'

const FILTERS = ['', 'STRONG', 'MODERATE', 'WEAK', 'INSUFFICIENT EVIDENCE']

export default function Relationships() {
  const [rels, setRels] = useState(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api('/relationships').then(setRels).catch((e) => setErr(e.message))
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!rels) return <Spinner />

  const shown = filter ? rels.filter((r) => r.strength === filter) : rels

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
