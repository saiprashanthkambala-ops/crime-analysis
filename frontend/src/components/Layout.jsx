import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ThemeToggle } from './ui'
import appLogo from '../profil icon'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [showUserMenu, setShowUserMenu] = useState(false)

  const onSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate('/search?q=' + encodeURIComponent(query.trim()))
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <NavLink to="/" className="brand-link" title="Crime Analysis Intelligence Platform">
            <img src={appLogo} alt="Crime Analysis Logo" className="brand-logo" />
            <span className="brand-text">Crime Analysis</span>
          </NavLink>
        </div>

        <form className="global-search" onSubmit={onSearch}>
          <div className="search-input-wrapper">
            <svg className="search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search person / case / phone / identifier…"
            />
            <kbd className="search-shortcut">⌘ K</kbd>
          </div>
        </form>

        <nav className="topnav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/cases">Cases</NavLink>
          <NavLink to="/analysis">Analysis</NavLink>
          <NavLink to="/relationships">Connections</NavLink>
          <NavLink to="/timeline">Timeline</NavLink>
          <NavLink to="/graph">Network</NavLink>
          <NavLink to="/evidence">Evidence</NavLink>
          <NavLink to="/import">Import</NavLink>
          {user?.role === 'admin' && <NavLink to="/admin">Admin</NavLink>}
        </nav>

        <div className="user-chip">
          <ThemeToggle />

          <button
            type="button"
            className="topbar-icon-btn"
            title="Investigation Alerts"
            aria-label="Investigation Alerts"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            <span className="notification-dot" />
          </button>

          <div className="user-dropdown-container">
            <button
              type="button"
              className="user-profile-badge"
              onClick={() => setShowUserMenu(!showUserMenu)}
              aria-label="User menu"
            >
              <img src={appLogo} alt="User Avatar" className="user-avatar-mini" />
              <span className="user-name-badge">{user?.full_name || user?.username || 'System Admin'}</span>
              <svg className="user-chevron" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {showUserMenu && (
              <div className="user-dropdown-menu">
                <div className="user-dropdown-header">
                  <div className="user-dropdown-name">{user?.full_name || 'System Administrator'}</div>
                  <div className="user-dropdown-role">{user?.role || 'Intelligence Analyst'}</div>
                </div>
                <div className="user-dropdown-divider" />
                <button
                  className="user-dropdown-item logout"
                  onClick={() => {
                    setShowUserMenu(false)
                    logout()
                    navigate('/login')
                  }}
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                  <span>Log out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <main className="content"><Outlet /></main>
    </div>
  )
}