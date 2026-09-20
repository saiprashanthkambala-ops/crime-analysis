import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ThemeToggle, Spinner } from './ui'\nimport { api } from '../api'
import appLogo from '../profil icon'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [accessOpen, setAccessOpen] = useState(false)
  const [investigatorOverview, setInvestigatorOverview] = useState(null)
  const [accessError, setAccessError] = useState('')

  useEffect(() => {
    if (!accessOpen) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setAccessOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    if (user?.role !== 'admin') {
      return () => document.removeEventListener('keydown', onKeyDown)
    }

    let active = true
    setAccessError('')
    api('/admin/investigators/overview')
      .then((data) => { if (active) setInvestigatorOverview(data) })
      .catch((e) => { if (active) setAccessError(e.message) })
    return () => {
      active = false
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [accessOpen, user?.role])

  const onSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate('/search?q=' + encodeURIComponent(query.trim()))
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <NavLink to="/" className="brand-link">
            <img src={appLogo} alt="Crime Analysis Logo" className="brand-logo" />
            <span className="brand-text">Crime Analysis</span>
          </NavLink>
        </div>
        <form className="global-search" onSubmit={onSearch}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search person / case / phone / identifier…" />
        </form>
        <nav className="topnav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/cases">Cases</NavLink>
          <NavLink to="/import">Import Data</NavLink>
          <NavLink to="/analysis">Analysis</NavLink>
          <NavLink to="/relationships">Connections</NavLink>
          <NavLink to="/timeline">Timeline</NavLink>
          <NavLink to="/graph">Network</NavLink>
          <NavLink to="/evidence">Evidence</NavLink>
          {user?.role === 'admin' && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="user-chip">
          <ThemeToggle />
          <button
            type="button"
            className="user-profile-badge user-profile-badge-button"
            onClick={() => setAccessOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={accessOpen}
          >
            <img src={appLogo} alt="User Avatar" className="user-avatar-mini" />
            <span className="user-name-badge">{user?.full_name || user?.username}</span>
          </button>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>Logout</button>
        </div>
      </header>
      <main className="content"><Outlet /></main>

      {accessOpen && (
        <div
          className="access-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAccessOpen(false)
          }}
        >
          <div className="access-modal" role="dialog" aria-modal="true" aria-labelledby="access-modal-title">
            <div className="access-modal-head">
              <div>
                <div className="access-modal-eyebrow">Account access</div>
                <h3 id="access-modal-title">Choose access type</h3>
                <p>Use your assigned account type. Passwords are never displayed in this interface.</p>
              </div>
              <button
                type="button"
                className="access-modal-close"
                onClick={() => setAccessOpen(false)}
                aria-label="Close access menu"
              >×</button>
            </div>

            <div className="access-role-grid">
              <div className={'access-role-card ' + (user?.role === 'admin' ? 'is-current' : '')}>
                <div className="access-role-title">System Admin</div>
                <div className="access-role-subtitle">
                  {user?.role === 'admin' ? 'Current signed-in role' : 'Restricted for this account'}
                </div>
                {user?.role === 'admin' ? (
                  <button type="button" className="btn btn-primary" onClick={() => { setAccessOpen(false); navigate('/admin') }}>
                    Open Admin Console
                  </button>
                ) : (
                  <span className="access-role-disabled">Administrator access required</span>
                )}
              </div>

              <div className={'access-role-card ' + (user?.role === 'investigator' ? 'is-current' : '')}>
                <div className="access-role-title">Investigator</div>
                <div className="access-role-subtitle">
                  {user?.role === 'investigator'
                    ? 'Current investigator interface'
                    : 'Separate investigator account'}
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => { setAccessOpen(false); navigate(user?.role === 'investigator' ? '/analysis' : '/login') }}
                >
                  {user?.role === 'investigator' ? 'Open Investigator Workspace' : 'Sign in as Investigator'}
                </button>
              </div>
            </div>

            {user?.role === 'admin' && (
              <div className="access-investigator-section">
                <div className="access-section-head">
                  <div>
                    <strong>Investigator Access Overview</strong>
                    <div className="muted small">Accounts, assigned cases, and recent case activity.</div>
                  </div>
                  <span className="badge role-badge">
                    {investigatorOverview?.investigators?.length ?? 0} investigators
                  </span>
                </div>

                {accessError && <div className="error-box small">{accessError}</div>}
                {!accessError && !investigatorOverview && <Spinner label="Loading investigator access…" />}
                {investigatorOverview?.investigators?.length === 0 && (
                  <div className="empty muted">No investigator accounts have been created.</div>
                )}

                <div className="access-investigator-list">
                  {(investigatorOverview?.investigators || []).map((investigator) => (
                    <div className="access-investigator-row" key={investigator.id}>
                      <div className="access-investigator-main">
                        <div className="access-investigator-name">
                          <strong>{investigator.full_name || investigator.username}</strong>
                          <span className="mono small">@{investigator.username}</span>
                        </div>
                        <div className="muted small">
                          {investigator.is_active ? 'Active account' : 'Inactive account'}
                          {investigator.email ? ' · ' + investigator.email : ''}
                        </div>
                        <div className="access-case-chips">
                          {(investigator.assigned_cases || []).map((item) => (
                            <span className="access-case-chip" key={item.id}>
                              {item.name} <span className="mono">{item.id}</span>
                            </span>
                          ))}
                          {!investigator.assigned_cases?.length && (
                            <span className="muted small">No cases assigned</span>
                          )}
                        </div>
                      </div>
                      <div className="access-investigator-meta">
                        <div className="muted small">Last login</div>
                        <strong>{investigator.last_login ? new Date(investigator.last_login).toLocaleString() : 'No recorded login'}</strong>
                        <div className="muted small">Last activity</div>
                        <strong>{investigator.last_activity ? new Date(investigator.last_activity).toLocaleString() : 'No recorded activity'}</strong>
                        {investigator.recent_case_activity?.length > 0 && (
                          <div className="access-recent-activity">
                            Recent: {investigator.recent_case_activity[0].action} · {investigator.recent_case_activity[0].case_name}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="access-modal-foot muted small">
              Login credentials are intentionally protected. The admin view exposes usernames, account status, assigned cases, and audit-derived activity, not passwords.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}