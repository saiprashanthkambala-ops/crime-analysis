import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge, Empty, KV } from '../components/ui'
import { useI18n } from '../i18n'

function IdList({ title, items, emptyText }) {
  return (
    <div className="id-block">
      <div className="id-title">{title}</div>
      {items.length === 0
        ? <div className="muted small">{emptyText}</div>
        : items.map((it, i) => <div key={i} className="id-chip mono">{it}</div>)}
    </div>
  )
}

export default function Profile() {
  const { t } = useI18n()
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
    <div className="page app-section-page">
      <div className="profile-head">
        <h2>{profile.name}</h2>
        <span className="muted mono">{profile.person_id}</span>
      </div>

      <div className="stat-grid">
        <div className="stat-card"><div className="stat-value">{c.phones}</div><div className="stat-label">{t('stat_phones')}</div></div>
        <div className="stat-card"><div className="stat-value">{c.vehicles}</div><div className="stat-label">{t('stat_vehicles')}</div></div>
        <div className="stat-card"><div className="stat-value">{c.accounts}</div><div className="stat-label">{t('stat_bank_accounts')}</div></div>
        <div className="stat-card"><div className="stat-value">{c.locations}</div><div className="stat-label">{t('stat_locations')}</div></div>
        <div className="stat-card"><div className="stat-value">{c.cases}</div><div className="stat-label">{t('stat_cases')}</div></div>
        <div className="stat-card"><div className="stat-value">{c.events}</div><div className="stat-label">{t('stat_calls_events')}</div></div>
      </div>

      {profile.resolution && profile.resolution.merged && (
        <Panel title={t('panel_identity_resolution')}>
          <div className="resolution-box">
            <div className="muted small">
              {t('identity_resolution_desc')}
            </div>
            <div className="source-list" style={{ marginTop: 8 }}>
              {(profile.resolution.variants || []).map((v) => (
                <span key={v} className="source-chip">{v}</span>
              ))}
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>
              {t('resolution_signals_confidence', {
                signals: (profile.resolution.signals || []).join(', ') || 'name similarity',
                confidence: Math.round((profile.resolution.confidence || 0) * 100),
              })}
            </div>
          </div>
        </Panel>
      )}

      <div className="two-col">
        <Panel title={t('panel_identifiers')}>
          <IdList title={t('stat_phones')} items={profile.phones} emptyText={t('unavailable')} />
          <IdList title={t('stat_vehicles')} items={profile.vehicles} emptyText={t('unavailable')} />
          <IdList title={t('stat_bank_accounts')} items={profile.accounts} emptyText={t('unavailable')} />
          <IdList title={t('stat_locations')} items={profile.locations} emptyText={t('unavailable')} />
          <div className="small muted" style={{ marginTop: 8 }}>
            {t('missing_attrs_disclaimer')}
          </div>
        </Panel>

        <Panel title={t('panel_connections')}>
          {profile.relationships.length === 0 && <Empty message={t('no_relationships_discovered')} />}
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

      <Panel title={t('panel_timeline')}>
        {profile.events.length === 0 && <Empty message={t('no_timeline_events')} />}
        <table className="table">
          <thead>
            <tr>
              <th>{t('col_date')}</th>
              <th>{t('col_time')}</th>
              <th>{t('col_type')}</th>
              <th>{t('description')}</th>
            </tr>
          </thead>
          <tbody>
            {profile.events.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">{t('unavailable')}</span>}</td>
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
