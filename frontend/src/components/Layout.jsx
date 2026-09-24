import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { useI18n } from '../i18n'
import { ThemeToggle, Spinner } from './ui'
import { api } from '../api'
import appLogo from '../profil icon'

export default function Layout() {
  const { user, logout } = useAuth()
  const { language, setLanguage, t } = useI18n()
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
            <span className="brand-text">{t('brand_title')}</span>
          </NavLink>
        </div>
        <form className="global-search" onSubmit={onSearch}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('search_placeholder')} />
        </form>
        <nav className="topnav">
          <NavLink to="/" end>{t('nav_dashboard')}</NavLink>
          <NavLink to="/cases">{t('nav_cases')}</NavLink>
          <NavLink to="/import">{t('nav_import')}</NavLink>
          <NavLink to="/analysis">{t('nav_analysis')}</NavLink>
          <NavLink to="/relationships">{t('nav_connections')}</NavLink>
          <NavLink to="/timeline">{t('nav_timeline')}</NavLink>
          <NavLink to="/graph">{t('nav_network')}</NavLink>
          <NavLink to="/evidence">{t('nav_evidence')}</NavLink>
          {user?.role === 'admin' && <NavLink to="/admin">{t('nav_admin')}</NavLink>}
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
            <span className="user-name-badge">{user?.role === 'admin' ? t('system_admin') : t('investigator')}</span>
          </button>
          <button
            type="button"
            className="logout-icon-btn"
            onClick={() => { logout(); navigate('/login') }}
            title={t('logout')}
            aria-label={t('logout')}
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
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
                <div className="access-modal-eyebrow">{t('account_access')}</div>
                <h3 id="access-modal-title">{t('choose_access_type')}</h3>
                <p>{t('account_access_desc')}</p>
              </div>
              <div className="access-modal-header-actions">
                <div className="access-lang-buttons" role="group" aria-label={t('select_language')}>
                  <button
                    type="button"
                    className={`access-lang-btn ${language === 'en' ? 'is-active' : ''}`}
                    onClick={() => setLanguage('en')}
                    title="English"
                  >
                    EN
                  </button>
                  <button
                    type="button"
                    className={`access-lang-btn ${language === 'te' ? 'is-active' : ''}`}
                    onClick={() => setLanguage('te')}
                    title="Telugu"
                  >
                    తెలుగు
                  </button>
                  <button
                    type="button"
                    className={`access-lang-btn ${language === 'hi' ? 'is-active' : ''}`}
                    onClick={() => setLanguage('hi')}
                    title="Hindi"
                  >
                    हिन्दी
                  </button>
                  <button
                    type="button"
                    className={`access-lang-btn ${language === 'ta' ? 'is-active' : ''}`}
                    onClick={() => setLanguage('ta')}
                    title="Tamil"
                  >
                    தமிழ்
                  </button>
                </div>
                <button
                  type="button"
                  className="access-modal-close"
                  onClick={() => setAccessOpen(false)}
                  aria-label={t('close_access_menu')}
                >×</button>
              </div>
            </div>

            <div className="access-role-grid">
              <div className={'access-role-card ' + (user?.role === 'admin' ? 'is-current' : '')}>
                <div className="access-role-title">{t('system_admin')}</div>
                <div className="access-role-subtitle">
                  {user?.role === 'admin'
                    ? t('current_signed_in_role')
                    : t('signin_with_sysadmin')}
                </div>
                <button
                  type="button"
                  className={user?.role === 'admin' ? 'btn btn-primary' : 'btn'}
                  onClick={() => {
                    setAccessOpen(false)
                    if (user?.role === 'admin') navigate('/admin')
                    else navigate('/login?role=admin')
                  }}
                >
                  {user?.role === 'admin' ? t('open_admin_console') : t('signin_as_sysadmin')}
                </button>
              </div>

              <div className={'access-role-card ' + (user?.role === 'investigator' ? 'is-current' : '')}>
                <div className="access-role-title">{t('investigator')}</div>
                <div className="access-role-subtitle">
                  {user?.role === 'investigator'
                    ? t('current_investigator_interface')
                    : t('signin_with_investigator')}
                </div>
                <button
                  type="button"
                  className={user?.role === 'investigator' ? 'btn btn-primary' : 'btn'}
                  onClick={() => {
                    setAccessOpen(false)
                    if (user?.role === 'investigator') navigate('/analysis')
                    else navigate('/login?role=investigator')
                  }}
                >
                  {user?.role === 'investigator' ? t('open_investigator_workspace') : t('signin_as_investigator')}
                </button>
              </div>
            </div>

            {user?.role === 'admin' && (
              <div className="access-investigator-section">
                <div className="access-section-head">
                  <div>
                    <strong>{t('investigator_access_overview')}</strong>
                    <div className="muted small">{t('investigator_overview_desc')}</div>
                  </div>
                  <span className="badge role-badge">
                    {t('count_investigators', { count: investigatorOverview?.investigators?.length ?? 0 })}
                  </span>
                </div>

                {accessError && <div className="error-box small">{accessError}</div>}
                {!accessError && !investigatorOverview && <Spinner label={t('loading_investigator_access')} />}
                {investigatorOverview?.investigators?.length === 0 && (
                  <div className="empty muted">{t('no_investigator_accounts')}</div>
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
                          {investigator.is_active ? t('active_account') : t('inactive_account')}
                          {investigator.email ? ' · ' + investigator.email : ''}
                        </div>
                        <div className="access-case-chips">
                          {(investigator.assigned_cases || []).map((item) => (
                            <span className="access-case-chip" key={item.id}>
                              {item.name} <span className="mono">{item.id}</span>
                            </span>
                          ))}
                          {!investigator.assigned_cases?.length && (
                            <span className="muted small">{t('no_cases_assigned')}</span>
                          )}
                        </div>
                      </div>
                      <div className="access-investigator-meta">
                        <div className="muted small">{t('last_login')}</div>
                        <strong>{investigator.last_login ? new Date(investigator.last_login).toLocaleString() : t('no_recorded_login')}</strong>
                        <div className="muted small">{t('last_activity')}</div>
                        <strong>{investigator.last_activity ? new Date(investigator.last_activity).toLocaleString() : t('no_recorded_activity')}</strong>
                        {investigator.recent_case_activity?.length > 0 && (
                          <div className="access-recent-activity">
                            {t('recent_prefix')} {investigator.recent_case_activity[0].action} · {investigator.recent_case_activity[0].case_name}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="access-modal-foot muted small">
              {t('access_modal_foot')}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}