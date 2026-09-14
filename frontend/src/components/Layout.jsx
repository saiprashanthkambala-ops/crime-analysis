import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ThemeToggle } from './ui'
import { api } from '../api'
import appLogo from '../profil icon'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const onSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`)
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
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search person / case / phone / identifier…"
          />
        </form>
        <nav className="topnav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/cases">Cases</NavLink>
          <NavLink to="/import">Import Data</NavLink>
          <NavLink to="/relationships">Connections</NavLink>
          <NavLink to="/timeline">Timeline</NavLink>
          <NavLink to="/graph">Network</NavLink>
          <NavLink to="/evidence">Evidence</NavLink>
          {user?.role === 'admin' && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="user-chip">
          <ThemeToggle />
          <div className="user-profile-badge">
            <img src={appLogo} alt="User Avatar" className="user-avatar-mini" />
            <span className="user-name-badge">{user?.full_name || user?.username}</span>
          </div>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate('/login') }}>
            Logout
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
