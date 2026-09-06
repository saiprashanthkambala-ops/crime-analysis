export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      <span className="muted">{label}</span>
    </div>
  )
}

export function Empty({ message }) {
  return <div className="empty muted">{message || 'No data available.'}</div>
}

export function ErrorBox({ message }) {
  return <div className="error-box">⚠ {message || 'Something went wrong.'}</div>
}

export function StrengthBadge({ strength }) {
  const cls = (strength || '').toLowerCase().replace(/\s+/g, '-')
  return <span className={`badge strength-${cls}`}>{strength || 'UNKNOWN'}</span>
}

export function TypeBadge({ type }) {
  return <span className={`badge type-badge`}>{type}</span>
}

export function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint muted">{hint}</div>}
    </div>
  )
}

export function Panel({ title, actions, children }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

export function KV({ k, v }) {
  return (
    <div className="kv">
      <span className="kv-key muted">{k}</span>
      <span className="kv-val">{v ?? <span className="muted">Unavailable</span>}</span>
    </div>
  )
}
