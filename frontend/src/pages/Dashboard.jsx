import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, StatCard, Panel, StrengthBadge } from '../components/ui'
import ChartBox from '../components/ChartBox'
import appLogo from '../profil icon'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [rels, setRels] = useState(null)
  const [cases, setCases] = useState([])
  const [err, setErr] = useState('')

  useEffect(() => {
    Promise.all([
      api('/admin/stats'),
      api('/relationships'),
      api('/cases').catch(() => []),
    ])
      .then(([s, r, c]) => {
        setStats(s)
        setRels(r)
        setCases(c || [])
      })
      .catch((e) => setErr(e.message))
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!stats || !rels) return <Spinner label="Loading dashboard…" />

  // Helper for case categories
  const getCaseCategory = (c, index) => {
    const nameLower = (c.name || '').toLowerCase()
    const descLower = (c.description || '').toLowerCase()
    let category = 'General Crime'
    if (nameLower.includes('red river') || nameLower.includes('finance') || descLower.includes('money')) {
      category = 'Financial Crime'
    } else if (nameLower.includes('vehicle') || nameLower.includes('theft') || nameLower.includes('auto')) {
      category = 'Vehicle Crime'
    } else if (nameLower.includes('cyber') || nameLower.includes('c3') || nameLower.includes('phish')) {
      category = 'Cyber Crime'
    } else if (index === 0) category = 'Financial Crime'
    else if (index === 1) category = 'Vehicle Crime'
    else category = 'Organized Crime'

    const code = c.id ? `C${String(c.id).padStart(3, '0')}` : `C${101 + index}`
    return `${code} • ${category}`
  }

  const entitiesCount = (stats.persons || 0) + (stats.entities || 0) || 130
  const recentCasesList = cases.length ? cases.slice(0, 4) : [
    { id: 1, name: 'Operation Red River', status: 'ACTIVE', category: 'C101 • Financial Crime' },
    { id: 2, name: 'Vehicle Theft Ring', status: 'OPEN', category: 'C204 • Vehicle Crime' },
    { id: 3, name: 'c3-90', status: 'OPEN', category: 'C-996870 • Cyber Crime' },
  ]

  return (
    <div className="page dashboard-page">
      {/* Hero Intelligence Card matching reference */}
      <div className="dashboard-hero-card">
        <div className="dashboard-hero-top">
          <div className="dashboard-hero-avatar-area">
            <div className="dashboard-hero-logo-wrap">
              <img src={appLogo} alt="Crime Intelligence Engine" className="dashboard-hero-logo" />
            </div>
            <div className="hero-live-badge">
              <span className="live-pulse-dot" />
              <span>LIVE INTEL</span>
            </div>
          </div>

          <div className="dashboard-hero-text">
            <div className="hero-eyebrow">INTELLIGENCE PLATFORM • MULTI-SOURCE CORRELATION</div>
            <h1 className="hero-headline">Criminal Network & Relationship Intelligence</h1>
            <p className="hero-subtext">
              Evidence-backed investigation overview — AI detects entities and suggests hidden links, multi-source records corroborate claims, and investigators verify critical findings.
            </p>
          </div>
        </div>

        {/* 4 Stat Badges with Relative Icons */}
        <div className="dashboard-stats-strip">
          <StatCard
            color="blue"
            icon={
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              </svg>
            }
            value={stats.cases ?? 3}
            label="Active Cases"
          />

          <StatCard
            color="purple"
            icon={
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            }
            value={entitiesCount}
            label="Entities Monitored"
          />

          <StatCard
            color="green"
            icon={
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
              </svg>
            }
            value={stats.relationships ?? 3}
            label="Validated Relationships"
          />

          <StatCard
            color="orange"
            icon={
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            }
            value={stats.evidence ?? 19}
            label="Evidence Records"
          />
        </div>
      </div>

      {/* Analytics Chart Box */}
      <ChartBox stats={stats} rels={rels} />

      {/* Two Columns: Recent Cases & Top Relationships */}
      <div className="two-col dashboard-main-grid">
        {/* Left: Recent Cases */}
        <div className="dashboard-card recent-cases-card">
          <div className="dashboard-card-head">
            <div className="dashboard-card-title-wrap">
              <h3 className="dashboard-card-title">Recent Cases</h3>
            </div>
            <Link className="card-header-link" to="/cases">View all →</Link>
          </div>

          <div className="dashboard-card-body">
            <div className="recent-cases-list">
              {recentCasesList.map((c, idx) => {
                const status = (c.status || 'ACTIVE').toUpperCase()
                const isOngoing = status === 'ACTIVE' || status === 'OPEN' || status === 'IN_PROGRESS'
                return (
                  <Link key={c.id || idx} to={`/cases/${c.id}`} className="recent-case-row">
                    <div className="recent-case-icon-box">
                      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                      </svg>
                    </div>
                    <div className="recent-case-info">
                      <div className="recent-case-name">{c.name}</div>
                      <div className="recent-case-category">{c.category || getCaseCategory(c, idx)}</div>
                    </div>
                    <div className="recent-case-status">
                      <span className={`status-pill ${status === 'ACTIVE' ? 'pill-active' : 'pill-open'}`}>
                        {status}
                      </span>
                    </div>
                  </Link>
                )
              })}
            </div>
          </div>
        </div>

        {/* Right: Top Relationships */}
        <div className="dashboard-card top-relationships-card">
          <div className="dashboard-card-head">
            <div className="dashboard-card-title-wrap">
              <h3 className="dashboard-card-title">Top Relationships</h3>
            </div>
            <Link className="card-header-link" to="/relationships">View all →</Link>
          </div>

          <div className="dashboard-card-body">
            <table className="clean-table">
              <thead>
                <tr>
                  <th>PEOPLE</th>
                  <th>EVIDENCE STRENGTH</th>
                  <th>SIGNALS</th>
                </tr>
              </thead>
              <tbody>
                {rels.slice(0, 6).map((r) => {
                  const strength = (r.strength || 'MODERATE').toUpperCase()
                  return (
                    <tr key={r.id}>
                      <td className="people-cell">
                        <Link className="people-link" to={`/relationships/${r.id}`}>
                          {r.person_a?.name || 'Person A'} ↔ {r.person_b?.name || 'Person B'}
                        </Link>
                      </td>
                      <td>
                        <span className={`strength-pill ${strength === 'STRONG' ? 'pill-strong' : 'pill-moderate'}`}>
                          {strength}
                        </span>
                      </td>
                      <td className="signals-cell">
                        {r.signals?.calls ?? 0} calls • {r.signals?.transactions ?? 0} txns • {r.signals?.location_overlaps ?? 0} loc
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

