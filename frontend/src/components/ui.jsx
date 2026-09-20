import { useTheme } from '../theme'

export function ThemeToggle({ className = '', showLabel = true }) {
  const { theme, toggleTheme } = useTheme()
  return (
    <button
      type="button"
      className={`theme-toggle-btn ${className}`.trim()}
      onClick={toggleTheme}
      title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
      aria-label="Toggle theme"
    >
      {theme === 'dark' ? (
        <>
          <svg className="theme-toggle-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
          {showLabel && <span className="theme-toggle-label">Light</span>}
        </>
      ) : (
        <>
          <svg className="theme-toggle-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
          {showLabel && <span className="theme-toggle-label">Dark</span>}
        </>
      )}
    </button>
  )
}

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

export function StatCard({ label, value, hint, icon, onClick, className = '' }) {
  const interactive = typeof onClick === 'function'
  const classes = ['stat-card', interactive ? 'stat-card-interactive' : '', className].filter(Boolean).join(' ')

  return (
    <div
      className={classes}
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={interactive ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(e)
        }
      } : undefined}
    >
      {icon && <div className="stat-icon" aria-hidden="true">{icon}</div>}
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint muted">{hint}</div>}
    </div>
  )
}

export function Panel({ title, actions, children, className = '' }) {
  return (
    <div className={`panel ${className}`.trim()}>
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
