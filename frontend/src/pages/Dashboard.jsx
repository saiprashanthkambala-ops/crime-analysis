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
  return <svg {...common} className={'metric-icon metric-icon-' + type}>{paths[type]}</svg>
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [rels, setRels] = useState(null)
  const [cases, setCases] = useState([])
  const [persons, setPersons] = useState([])
  const [evidence, setEvidence] = useState([])
  const [documents, setDocuments] = useState([])
  const [entities, setEntities] = useState([])
  const [err, setErr] = useState('')
  const [activeMetric, setActiveMetric] = useState(null)

  useEffect(() => {
    Promise.all([
      api('/admin/stats'),
      api('/relationships'),
      api('/cases'),
      api('/persons'),
      api('/evidence'),
      api('/entities'),
    ])
      .then(([s, r, c, p, e, entityRows]) => {
        setStats(s)
        setRels(r)
        setCases(c)
        setPersons(p)
        setEvidence(e)
        setDocuments(c.flatMap((item) => (item.documents || []).map((doc) => ({
          ...doc,
          case_id: item.id,
          case_name: item.name,
        }))))
        setEntities(entityRows)
      })
      .catch((e) => setErr(e.message))
  }, [])

  useEffect(() => {
    if (!activeMetric) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setActiveMetric(null)
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [activeMetric])

  const metricItems = {
    cases,
    persons,
    relationships: rels || [],
    evidence,
    documents,
    entities,
  }

  const metricMeta = {
    cases: { title: 'Active Cases', description: 'Current cases available to the signed-in investigator.', icon: 'cases' },
    persons: { title: 'Persons', description: 'People represented in the investigation data.', icon: 'persons' },
    relationships: { title: 'Relationships', description: 'Stored evidence-backed person-to-person relationships.', icon: 'relationships' },
    evidence: { title: 'Evidence Records', description: 'Evidence records currently stored in the investigation database.', icon: 'evidence' },
    documents: { title: 'Documents', description: 'Imported source documents associated with cases.', icon: 'documents' },
    entities: { title: 'Extracted Entities', description: 'Entities extracted and normalized from imported source material.', icon: 'entities' },
  }

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
        <StatCard label="Active Cases" value={stats.cases} icon={<MetricIcon type="cases" />} onClick={() => setActiveMetric('cases')} />
        <StatCard label="Persons" value={stats.persons} icon={<MetricIcon type="persons" />} onClick={() => setActiveMetric('persons')} />
        <StatCard label="Relationships" value={stats.relationships} icon={<MetricIcon type="relationships" />} onClick={() => setActiveMetric('relationships')} />
        <StatCard label="Evidence Records" value={stats.evidence} icon={<MetricIcon type="evidence" />} onClick={() => setActiveMetric('evidence')} />
        <StatCard label="Documents" value={stats.documents} icon={<MetricIcon type="documents" />} onClick={() => setActiveMetric('documents')} />
        <StatCard label="Extracted Entities" value={stats.entities} icon={<MetricIcon type="entities" />} onClick={() => setActiveMetric('entities')} />
      </div>

      {activeMetric && (
        <div
          className="dashboard-metric-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setActiveMetric(null)
          }}
        >
          <div
            className="dashboard-metric-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dashboard-metric-title"
          >
            <div className="dashboard-metric-modal-head">
              <div>
                <div className="dashboard-metric-eyebrow">Dashboard details</div>
                <h3 id="dashboard-metric-title">{metricMeta[activeMetric].title}</h3>
                <p>{metricMeta[activeMetric].description}</p>
              </div>
              <button
                type="button"
                className="dashboard-metric-close"
                onClick={() => setActiveMetric(null)}
                aria-label="Close details"
              >
                ×
              </button>
            </div>

            <div className="dashboard-metric-modal-body">
              <div className="dashboard-metric-summary">
                <div className={'dashboard-metric-icon metric-icon-' + metricMeta[activeMetric].icon}>
                  <MetricIcon type={metricMeta[activeMetric].icon} />
                </div>
                <div>
                  <div className="dashboard-metric-count">{(metricItems[activeMetric] || []).length}</div>
                  <div className="muted small">{metricMeta[activeMetric].title}</div>
                </div>
              </div>

              {activeMetric === 'cases' && (
                <div className="dashboard-detail-list">
                  {cases.map((item) => (
                    <div className="dashboard-detail-row" key={item.id}>
                      <div>
                        <strong>{item.name}</strong>
                        <div className="muted small mono">{item.id}</div>
                      </div>
                      <span className={'badge status-' + String(item.status || '').toLowerCase()}>{item.status}</span>
                    </div>
                  ))}
                </div>
              )}

              {activeMetric === 'persons' && (
                <div className="dashboard-detail-list">
                  {persons.map((item) => (
                    <div className="dashboard-detail-row" key={item.person_id}>
                      <div>
                        <strong>{item.name}</strong>
                        <div className="muted small mono">{item.person_id}</div>
                      </div>
                      <span className="dashboard-detail-type">Person</span>
                    </div>
                  ))}
                </div>
              )}

              {activeMetric === 'relationships' && (
                <div className="dashboard-detail-list">
                  {rels.slice(0, 30).map((item) => (
                    <div className="dashboard-detail-row dashboard-detail-row-stack" key={item.id}>
                      <div>
                        <strong>{item.person_a?.name} ↔ {item.person_b?.name}</strong>
                        <div className="muted small">
                          {(item.signals?.calls || 0)} calls · {(item.signals?.transactions || 0)} txns · {(item.signals?.location_overlaps || 0)} location overlaps
                        </div>
                      </div>
                      <div className="dashboard-detail-side">
                        <span className="badge status-badge">{item.strength || '—'}</span>
                        <span className="mono small">score {item.score ?? '—'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeMetric === 'evidence' && (
                <div className="dashboard-detail-list">
                  {evidence.map((item) => (
                    <div className="dashboard-detail-row dashboard-detail-row-stack" key={item.id}>
                      <div>
                        <strong>{item.type || 'Evidence record'}</strong>
                        <div className="muted small">{item.source || 'Source not specified'}</div>
                      </div>
                      <div className="dashboard-detail-side">
                        <span className="muted small">{item.date || 'Date unavailable'}</span>
                        <span className="mono small">{item.id}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeMetric === 'documents' && (
                <div className="dashboard-detail-list">
                  {documents.map((item) => (
                    <div className="dashboard-detail-row dashboard-detail-row-stack" key={item.id}>
                      <div>
                        <strong>{item.filename}</strong>
                        <div className="muted small">{item.case_name} · {item.file_type || 'file'}</div>
                      </div>
                      <div className="dashboard-detail-side">
                        <span className="badge status-badge">{item.status}</span>
                        <span className="mono small">{item.id}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeMetric === 'entities' && (
                <div className="dashboard-detail-list">
                  {entities.slice(0, 60).map((item) => (
                    <div className="dashboard-detail-row dashboard-detail-row-stack" key={item.id}>
                      <div>
                        <strong>{item.value || 'Unknown value'}</strong>
                        <div className="muted small">{item.case_id || 'No case'} · {item.normalized || 'Not normalized'}</div>
                      </div>
                      <span className="dashboard-detail-type">{item.type || 'Entity'}</span>
                    </div>
                  ))}
                  {entities.length > 60 && (
                    <div className="empty muted small">
                      Showing 60 of {entities.length} extracted entities.
                    </div>
                  )}
                </div>
              )}

              {metricItems[activeMetric]?.length === 0 && (
                <div className="empty muted">No records are available for this metric.</div>
              )}
            </div>
          </div>
        </div>
      )}

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
