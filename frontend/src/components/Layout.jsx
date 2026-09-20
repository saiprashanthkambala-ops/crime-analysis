import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ThemeToggle } from './ui'
import appLogo from '../profil icon'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [accountOpen, setAccountOpen] = useState(false)
  const [adminUsers, setAdminUsers] = useState([])
  const [adminCases, setAdminCases] = useState([])
  const [auditLogs, setAuditLogs] = useState([])
  const [adminLoading, setAdminLoading] = useState(false)
  const [adminError, setAdminError] = useState('')

  const onSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate('/search?q=' + encodeURIComponent(query.trim()))
  }

  const openAccount = async () => {
    setAccountOpen(true)
    if (user?.role !== 'admin' || adminUsers.length) return
    setAdminLoading(true)
    setAdminError('')
    try {
      const [users, cases, logs] = await Promise.all([
        api('/admin/users'),
        api('/admin/cases'),
        api('/audit'),
      ])
      setAdminUsers(users)
      setAdminCases(cases)
      setAuditLogs(logs)
    } catch (error) {
      setAdminError(error.message)
    } finally {
      setAdminLoading(false)
    }
  }

  useEffect(() => {
    if (!accountOpen) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [accountOpen])

  const investigators = adminUsers.filter((item) => item.role === 'investigator')
  const investigatorAudit = new Map()
  for (const item of auditLogs) {
    if (!item.user) continue
    const existing = investigatorAudit.get(item.user)
    if (!existing) investigatorAudit.set(item.user, item)
  }

  const signInAsInvestigator = () => {
    logout()
    setAccountOpen(false)
    navigate('/login')
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
          {user?.role === 'admin' ? (
            <button
              type="button"
              className="user-profile-badge user-profile-button"
              onClick={openAccount}
              title="Open account and access controls"
            >
              <img src={appLogo} alt="User Avatar" className="user-avatar-mini" />
              <span className="user-name-badge">{user?.full_name || user?.username}</span>
            </button>
          ) : (
            <div className="user-profile-badge">
              <img src={appLogo} alt="User Avatar" className="user-avatar-mini" />
              <span className="user-name-badge">{user?.full_name || user?.username}</span>
            </div>
          )}
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>Logout</button>
        </div>
      </header>

      {accountOpen && user?.role === 'admin' && (
        <div
          className="account-access-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAccountOpen(false)
          }}
        >
          <div className="account-access-modal" role="dialog" aria-modal="true" aria-labelledby="account-access-title">
            <div className="account-access-head">
              <div>
                <div className="account-access-eyebrow">Access & workspace</div>
                <h3 id="account-access-title">System Admin</h3>
                <p>Manage the administrator workspace and review investigator access.</p>
              </div>
              <button type="button" className="account-access-close" onClick={() => setAccountOpen(false)} aria-label="Close">×</button>
            </div>

            <div className="account-access-body">
              <div className="account-role-switcher">
                <div className="account-role-card is-active">
                  <div className="account-role-title">System Admin</div>
                  <div className="muted small">{user?.full_name || user?.username}</div>
                  <div className="account-role-desc">Full application access, including Administration.</div>
                </div>
                <div className="account-role-card">
                  <div className="account-role-title">Investigator</div>
                  <div className="muted small">Investigator workspace</div>
                  <div className="account-role-desc">Same investigation pages; Administration is hidden.</div>
                  <button type="button" className="btn" onClick={signInAsInvestigator}>Open Investigator Login</button>
                </div>
              </div>

              {adminLoading ? (
                <div className="empty muted">Loading investigator access details…</div>
              ) : adminError ? (
                <div className="error-box">{adminError}</div>
              ) : (
                <>
                  <div className="account-section">
                    <div className="account-section-title">Investigators & assigned cases</div>
                    <div className="account-table-scroll">
                      <table className="table">
                        <thead>
                          <tr><th>Investigator</th><th>Email</th><th>Status</th><th>Assigned Cases</th><th>Last Activity</th></tr>
                        </thead>
                        <tbody>
                          {investigators.map((item) => {
                            const assigned = adminCases.filter((itemCase) => itemCase.assigned.includes(item.id))
                            const last = investigatorAudit.get(item.username)
                            return (
                              <tr key={item.id}>
                                <td>
                                  <strong>{item.full_name || item.username}</strong>
                                  <div className="muted small mono">{item.username}</div>
                                </td>
                                <td>{item.email || '—'}</td>
                                <td><span className="badge role-badge">{item.is_active ? 'Active' : 'Disabled'}</span></td>
                                <td>
                                  {assigned.length
                                    ? assigned.map((itemCase) => <span key={itemCase.id} className="account-case-chip">{itemCase.name}</span>)
                                    : <span className="muted small">No cases assigned</span>}
                                </td>
                                <td className="small">
                                  {last ? (
                                    <>
                                      <div>{last.action}</div>
                                      <div className="muted">{last.created_at ? new Date(last.created_at).toLocaleString() : '—'}</div>
                                    </>
                                  ) : 'No activity'}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="account-security-note">
                      Passwords are never displayed here. Investigator login credentials remain private; this panel shows usernames, account status, assigned cases, and recent activity.
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
      <main className="content"><Outlet /></main>
    </div>
  )
}