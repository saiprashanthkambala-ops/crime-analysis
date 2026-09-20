import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, StatCard, Panel, StrengthBadge } from '../components/ui'
import appLogo from '../profil icon'

const MetricIcon = ({ type }) => {
  const common = { viewBox: '0 0 24 24', width: 22, height: 22, fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }
  const paths = {
    cases: <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 5V3h8v2M8 10h8M8 14h5" /></>,
    persons: <><circle cx="12" cy="8" r="3" /><path d="M5 20c.7-3.3 3.1-5 7-5s6.3 1.7 7 5" /></>,
    relationships: <><circle cx="7" cy="12" r="2.5" /><circle cx="17" cy="7" r="2.5" /><circle cx="17" cy="17" r="2.5" /><path d="m9.2 10.9 5.6-2.8M9.2 13.1l5.6 2.8" /></>,
    evidence: <><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v5h4M9 13h6M9 17h4" /></>,
    documents: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h4M9 12h6M9 16h6" /></>,
    entities: <><circle cx="12" cy="12" r="3" /><circle cx="5" cy="7" r="2" /><circle cx="19" cy="7" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="m9.5 10.3-3-1.8M14.5 10.3l3-1.8M9.5 13.7l-3 2M14.5 13.7l3 2" /></>,
  }
  return <svg {...common}>{paths[type]}</svg>
}

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
        <StatCard label="Active Cases" value={stats.cases} icon={<MetricIcon type="cases" />} />
        <StatCard label="Persons" value={stats.persons} icon={<MetricIcon type="persons" />} />
        <StatCard label="Relationships" value={stats.relationships} icon={<MetricIcon type="relationships" />} />
        <StatCard label="Evidence Records" value={stats.evidence} icon={<MetricIcon type="evidence" />} />
        <StatCard label="Documents" value={stats.documents} icon={<MetricIcon type="documents" />} />
        <StatCard label="Extracted Entities" value={stats.entities} icon={<MetricIcon type="entities" />} />
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
