import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, StatCard, Panel, StrengthBadge } from '../components/ui'
import appLogo from '../profil icon'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [rels, setRels] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    Promise.all([api('/admin/stats'), api('/relationships')])
      .then(([s, r]) => { setStats(s); setRels(r) })
      .catch((e) => setErr(e.message))
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!stats || !rels) return <Spinner label="Loading dashboard…" />

  return (
    <div className="page dashboard-page">
      <div className="dashboard-hero">
        <div className="dashboard-hero-visual">
          <div className="dashboard-hero-img-wrapper">
            <img src={appLogo} alt="Crime Analysis Investigation Suite" className="dashboard-hero-img" />
            <div className="hero-badge-live">
              <span className="live-dot"></span> LIVE INTEL
            </div>
          </div>
        </div>
        <div className="dashboard-hero-content">
          <div className="hero-tag">INTELLIGENCE PLATFORM · MULTI-SOURCE CORROBORATION</div>
          <h1 className="hero-title">Criminal Network & Relationship Intelligence</h1>
          <p className="hero-description">
            Evidence-backed investigation overview — AI detects entities and suggests hidden links, multi-source records corroborate claims, and investigators verify critical findings.
          </p>
          <div className="hero-meta-strip">
            <div className="hero-meta-item">
              <span className="meta-label">Active Cases</span>
              <span className="meta-val">{stats.cases}</span>
            </div>
            <div className="hero-meta-divider"></div>
            <div className="hero-meta-item">
              <span className="meta-label">Total Entities Monitored</span>
              <span className="meta-val">{(stats.persons || 0) + (stats.entities || 0)}</span>
            </div>
            <div className="hero-meta-divider"></div>
            <div className="hero-meta-item">
              <span className="meta-label">Validated Relationships</span>
              <span className="meta-val">{stats.relationships}</span>
            </div>
            <div className="hero-meta-divider"></div>
            <div className="hero-meta-item">
              <span className="meta-label">Evidence Vault</span>
              <span className="meta-val">{stats.evidence} records</span>
            </div>
          </div>
        </div>
      </div>

      <div className="stat-grid">
        <StatCard label="Active Cases" value={stats.cases} />
        <StatCard label="Persons" value={stats.persons} />
        <StatCard label="Relationships" value={stats.relationships} />
        <StatCard label="Evidence Records" value={stats.evidence} />
        <StatCard label="Documents" value={stats.documents} />
        <StatCard label="Extracted Entities" value={stats.entities} />
      </div>

      <div className="two-col">
        <Panel title="Top Relationships" actions={<Link className="link" to="/relationships">View all →</Link>}>
          <table className="table">
            <thead>
              <tr><th>People</th><th>Evidence Strength</th><th>Signals</th></tr>
            </thead>
            <tbody>
              {rels.slice(0, 8).map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link className="link" to={`/relationships/${r.id}`}>
                      {r.person_a.name} ↔ {r.person_b.name}
                    </Link>
                  </td>
                  <td><StrengthBadge strength={r.strength} /></td>
                  <td className="muted">
                    {r.signals.calls} calls · {r.signals.transactions} txns · {r.signals.location_overlaps} loc
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Quick Actions">
          <div className="quick-actions">
            <Link className="btn btn-outline" to="/cases">Manage Cases</Link>
            <Link className="btn btn-outline" to="/graph">Open Network</Link>
            <Link className="btn btn-outline" to="/timeline">Open Timeline</Link>
            <Link className="btn btn-outline" to="/search">Search Records</Link>
          </div>
        </Panel>
      </div>
    </div>
  )
}
