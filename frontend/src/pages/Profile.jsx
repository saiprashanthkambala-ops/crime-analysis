import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge, Empty, KV } from '../components/ui'

function IdList({ title, items }) {
  return (
    <div className="id-block">
      <div className="id-title">{title}</div>
      {items.length === 0
        ? <div className="muted small">Unavailable</div>
        : items.map((it, i) => <div key={i} className="id-chip mono">{it}</div>)}
    </div>
  )
}

export default function Profile() {
  const { personId } = useParams()
  const [profile, setProfile] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api(`/persons/${personId}`).then(setProfile).catch((e) => setErr(e.message))
  }, [personId])

  if (err) return <ErrorBox message={err} />
  if (!profile) return <Spinner />

  const c = profile.counts

  return (
    <div className="page">
      <div className="profile-head">
        <h2>{profile.name}</h2>
        <span className="muted mono">{profile.person_id}</span>
      </div>

      <div className="stat-grid">
        <div className="stat-card"><div className="stat-value">{c.phones}</div><div className="stat-label">Phones</div></div>
        <div className="stat-card"><div className="stat-value">{c.vehicles}</div><div className="stat-label">Vehicles</div></div>
        <div className="stat-card"><div className="stat-value">{c.accounts}</div><div className="stat-label">Bank Accounts</div></div>
        <div className="stat-card"><div className="stat-value">{c.locations}</div><div className="stat-label">Locations</div></div>
        <div className="stat-card"><div className="stat-value">{c.cases}</div><div className="stat-label">Cases</div></div>
        <div className="stat-card"><div className="stat-value">{c.events}</div><div className="stat-label">Calls / Events</div></div>
      </div>

      <div className="two-col">
        <Panel title="Identifiers">
          <IdList title="Phones" items={profile.phones} />
          <IdList title="Vehicles" items={profile.vehicles} />
          <IdList title="Bank Accounts" items={profile.accounts} />
          <IdList title="Locations" items={profile.locations} />
          <div className="small muted" style={{ marginTop: 8 }}>
            Missing attributes are unknown — never negative evidence.
          </div>
        </Panel>

        <Panel title="Connections">
          {profile.relationships.length === 0 && <Empty message="No relationships discovered." />}
          <table className="table">
            <tbody>
              {profile.relationships.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link className="link" to={`/relationships/${r.id}`}>
                      {r.other_person_id}
                    </Link>
                  </td>
                  <td><StrengthBadge strength={r.strength} /></td>
                  {r.decision && <td className="muted">→ {r.decision}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <Panel title="Timeline">
        {profile.events.length === 0 && <Empty message="No timeline events available." />}
        <table className="table">
          <thead><tr><th>Date</th><th>Time</th><th>Type</th><th>Description</th></tr></thead>
          <tbody>
            {profile.events.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">Unavailable</span>}</td>
                <td><span className="badge type-badge">{e.type}</span></td>
                <td className="muted">{e.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
