import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'

export default function SearchPage() {
  const [params] = useSearchParams()
  const q = params.get('q') || ''
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!q) { setRes({ people: [], entities: [], cases: [] }); return }
    api(`/search?q=${encodeURIComponent(q)}`).then(setRes).catch((e) => setErr(e.message))
  }, [q])

  if (err) return <ErrorBox message={err} />
  if (!res) return <Spinner label={`Searching "${q}"…`} />

  const total = res.people.length + res.entities.length + res.cases.length

  return (
    <div className="page">
      <h2>Search results for “{q}”</h2>
      <p className="muted">{total} matches</p>

      <Panel title="People">
        {res.people.length === 0 && <Empty message="No matching people." />}
        <div className="result-list">
          {res.people.map((p) => (
            <Link key={p.person_id} className="result-item link" to={`/persons/${p.person_id}`}>
              <span className="result-type person">PERSON</span> {p.name}
            </Link>
          ))}
        </div>
      </Panel>

      <Panel title="Identifiers & Entities">
        {res.entities.length === 0 && <Empty message="No matching identifiers." />}
        <div className="result-list">
          {res.entities.map((e) => (
            <Link key={e.id} className="result-item link" to={`/search?q=${encodeURIComponent(e.value)}`}>
              <span className="result-type entity">{e.type}</span> {e.value}
              {e.case_id && <span className="muted small"> · {e.case_id}</span>}
            </Link>
          ))}
        </div>
      </Panel>

      <Panel title="Cases">
        {res.cases.length === 0 && <Empty message="No matching cases." />}
        <div className="result-list">
          {res.cases.map((c) => (
            <Link key={c.id} className="result-item link" to={`/cases/${c.id}`}>
              <span className="result-type case">CASE</span> {c.name} <span className="muted small">({c.id})</span>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  )
}
