import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'
import { useI18n } from '../i18n'

export default function AdminPage() {
  const { t } = useI18n()
  const [logs, setLogs] = useState(null)
  const [users, setUsers] = useState(null)
  const [cases, setCases] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const [nu, setNu] = useState({ username: '', password: '', full_name: '', email: '', role: 'investigator' })

  const load = () =>
    Promise.all([
      api('/audit'),
      api('/admin/users'),
      api('/admin/cases'),
      api('/admin/telemetry/ai').catch(() => null),
    ])
      .then(([l, u, c, tel]) => {
        setLogs(l)
        setUsers(u)
        setCases(c)
        if (tel) setTelemetry(tel)
      })
      .catch((e) => setErr(e.message))

  useEffect(() => { load() }, [])

  const createUser = async (e) => {
    e.preventDefault()
    if (!nu.username || !nu.password) return
    try {
      await api('/admin/users', { method: 'POST', body: JSON.stringify(nu) })
      setNu({ username: '', password: '', full_name: '', email: '', role: 'investigator' })
      setMsg(t('user_created_msg'))
      await load()
    } catch (err) { setErr(err.message) }
  }

  const assign = async (caseId, userId, action) => {
    try {
      await api(`/admin/cases/${caseId}/users`, {
        method: 'POST', body: JSON.stringify({ user_id: userId, action }),
      })
      await load()
    } catch (err) { setErr(err.message) }
  }

  if (err) return <ErrorBox message={err} />
  if (!logs || !users || !cases) return <Spinner />

  return (
    <div className="page app-section-page">
      <h2>{t('administration_title')}</h2>
      {msg && <div className="info-box">{msg}</div>}

      <div className="two-col">
        <Panel title={t('panel_audit_trail', { count: logs.length })}>
          {logs.length === 0 && <Empty message={t('no_audit_events')} />}
          <table className="table">
            <thead><tr><th>{t('col_time')}</th><th>{t('col_user')}</th><th>{t('col_action')}</th><th>{t('col_entity_header')}</th></tr></thead>
            <tbody>
              {logs.slice(0, 100).map((l) => (
                <tr key={l.id}>
                  <td className="mono small">{l.created_at ? new Date(l.created_at).toLocaleString() : ''}</td>
                  <td>{l.user || 'system'}</td>
                  <td>{l.action}</td>
                  <td className="mono small">{l.entity_type} {l.entity_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title={t('panel_users', { count: users.length })}>
            <table className="table">
              <thead><tr><th>{t('col_username')}</th><th>{t('col_full_name')}</th><th>{t('col_role')}</th><th>{t('col_active')}</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.full_name}</td>
                    <td><span className="badge role-badge">{u.role}</span></td>
                    <td>{u.is_active ? '✓' : '✕'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title={t('panel_create_user')}>
            <form onSubmit={createUser} className="form">
              <input placeholder={t('placeholder_username')} value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
              <input type="password" placeholder={t('placeholder_password')} value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
              <input placeholder={t('placeholder_fullname')} value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
              <input placeholder={t('placeholder_email')} value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
              <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
                <option value="investigator">{t('role_opt_investigator')}</option>
                <option value="admin">{t('role_opt_admin')}</option>
              </select>
              <button className="btn btn-primary">{t('btn_create_user')}</button>
            </form>
          </Panel>
        </div>
      </div>

      <Panel title={t('panel_case_access')}>
        <table className="table">
          <thead><tr><th>{t('col_case')}</th><th>{t('col_assigned_investigators')}</th></tr></thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id}>
                <td><b>{c.name}</b> <span className="muted mono">({c.id})</span></td>
                <td>
                  {users.map((u) => {
                    const on = c.assigned.includes(u.id)
                    return (
                      <button
                        key={u.id}
                        className={`btn btn-ghost small`}
                        style={{ marginRight: 4, background: on ? 'rgba(34,211,238,0.15)' : undefined }}
                        onClick={() => assign(c.id, u.id, on ? 'remove' : 'add')}
                        title={on ? t('tip_remove_access') : t('tip_grant_access')}
                      >
                        {on ? '✓' : ''} {u.username}
                      </button>
                    )
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {telemetry && (
        <Panel title={t('panel_ai_telemetry') || 'AI Latency & Intelligence Telemetry (Admin Only)'}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
            <div className="card" style={{ padding: 12, textAlign: 'center' }}>
              <div className="muted small">Total Requests</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 600 }}>{telemetry.total_requests}</div>
              <div className="muted" style={{ fontSize: '0.75rem' }}>{telemetry.successful_requests} ok / {telemetry.failed_requests} err</div>
            </div>
            <div className="card" style={{ padding: 12, textAlign: 'center' }}>
              <div className="muted small">TTFT (p50 / p95)</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 600 }}>
                {telemetry.ttft?.p50_ms != null ? `${Math.round(telemetry.ttft.p50_ms)}ms` : '—'}
                <span className="muted" style={{ fontSize: '0.9rem', fontWeight: 400 }}> / {telemetry.ttft?.p95_ms != null ? `${Math.round(telemetry.ttft.p95_ms)}ms` : '—'}</span>
              </div>
              <div className="muted" style={{ fontSize: '0.75rem' }}>avg: {telemetry.ttft?.avg_ms != null ? `${Math.round(telemetry.ttft.avg_ms)}ms` : '—'}</div>
            </div>
            <div className="card" style={{ padding: 12, textAlign: 'center' }}>
              <div className="muted small">Duration (p50 / p95)</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 600 }}>
                {telemetry.duration?.p50_ms != null ? `${(telemetry.duration.p50_ms / 1000).toFixed(1)}s` : '—'}
                <span className="muted" style={{ fontSize: '0.9rem', fontWeight: 400 }}> / {telemetry.duration?.p95_ms != null ? `${(telemetry.duration.p95_ms / 1000).toFixed(1)}s` : '—'}</span>
              </div>
              <div className="muted" style={{ fontSize: '0.75rem' }}>avg: {telemetry.duration?.avg_ms != null ? `${(telemetry.duration.avg_ms / 1000).toFixed(1)}s` : '—'}</div>
            </div>
            <div className="card" style={{ padding: 12, textAlign: 'center' }}>
              <div className="muted small">Fallback Usage</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 600 }}>{telemetry.fallback_rate_pct}%</div>
              <div className="muted" style={{ fontSize: '0.75rem' }}>{telemetry.fallback_count} invocations</div>
            </div>
          </div>

          <h4 style={{ margin: '12px 0 8px 0', fontSize: '0.9rem' }}>Recent Invocations</h4>
          {(!telemetry.recent_metrics || telemetry.recent_metrics.length === 0) ? (
            <Empty message="No AI requests recorded yet in this server session." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Endpoint</th>
                  <th>Model</th>
                  <th>TTFT</th>
                  <th>Total Time</th>
                  <th>Tokens</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {telemetry.recent_metrics.slice(-10).reverse().map((m, idx) => (
                  <tr key={idx}>
                    <td className="mono small">{new Date(m.timestamp).toLocaleTimeString()}</td>
                    <td><span className="badge">{m.endpoint}</span></td>
                    <td className="mono small" title={m.model}>
                      {m.model?.split('/').pop() || m.model}
                      {m.used_fallback && <span className="badge" style={{ marginLeft: 6, background: '#f59e0b' }}>fallback</span>}
                    </td>
                    <td className="mono small">{m.ttft_ms != null ? `${Math.round(m.ttft_ms)}ms` : '—'}</td>
                    <td className="mono small">{m.duration_ms != null ? `${(m.duration_ms / 1000).toFixed(2)}s` : '—'}</td>
                    <td className="mono small">{m.token_count ?? '—'}</td>
                    <td>
                      {m.success ? (
                        <span style={{ color: '#10b981' }}>✓ OK</span>
                      ) : (
                        <span style={{ color: '#ef4444' }}>✕ {m.error_type || 'Failed'}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}
    </div>
  )
}
