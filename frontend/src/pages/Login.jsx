import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth'
import { useI18n } from '../i18n'
import { ThemeToggle } from '../components/ui'
import appLogo from '../profil icon'

export default function Login() {
  const { login, logout } = useAuth()
  const { language, setLanguage, languages, t } = useI18n()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const urlRole = searchParams.get('role')
  const initialRole = urlRole === 'admin' || urlRole === 'investigator' ? urlRole : null

  const [selectedRole, setSelectedRole] = useState(initialRole)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (urlRole === 'admin' || urlRole === 'investigator') {
      setSelectedRole(urlRole)
    }
  }, [urlRole])

  const handleSelectRole = (role) => {
    setSelectedRole(role)
    setError('')
    setSearchParams(role ? { role } : {})
  }

  const handleResetRole = () => {
    setSelectedRole(null)
    setError('')
    setUsername('')
    setPassword('')
    setSearchParams({})
  }

  const handleAutofill = (role, demoUser, demoPass) => {
    setSelectedRole(role)
    setUsername(demoUser)
    setPassword(demoPass)
    setError('')
    setSearchParams({ role })
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!selectedRole) {
      setError(t('select_role_prompt'))
      return
    }
    setLoading(true)
    setError('')
    try {
      const signedInUser = await login(username, password)
      if (signedInUser.role !== selectedRole) {
        await logout()
        throw new Error(
          selectedRole === 'investigator'
            ? t('login_err_not_investigator')
            : t('login_err_not_admin')
        )
      }
      if (selectedRole === 'admin') {
        navigate('/admin')
      } else {
        navigate('/')
      }
    } catch (err) {
      setError(err.message || t('something_went_wrong'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-top-bar">
        <div className="login-lang-buttons" role="group" aria-label={t('select_language')}>
          {(languages || []).map((lang) => (
            <button
              key={lang.code}
              type="button"
              className={`login-lang-btn ${language === lang.code ? 'is-active' : ''}`}
              onClick={() => setLanguage(lang.code)}
              title={lang.name}
            >
              {lang.label}
            </button>
          ))}
        </div>
        <ThemeToggle />
      </div>

      <div className="login-container">
        <div className="login-card">
          <div className="login-brand">
            <div className="login-logo-container">
              <img src={appLogo} alt="Crime Analysis" className="login-logo-img" />
            </div>
            <h1>{t('brand_title')}</h1>
            <p className="muted">{t('login_ai_subtitle')}</p>
          </div>

          {!selectedRole ? (
            /* STEP 1: Select Role First */
            <div className="login-role-selection">
              <div className="login-role-prompt">{t('select_role_prompt')}</div>
              <div className="login-role-grid">
                <button
                  type="button"
                  className="login-role-choice role-admin"
                  onClick={() => handleSelectRole('admin')}
                >
                  <div className="login-role-icon-box">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                      <circle cx="12" cy="11" r="3" />
                      <path d="M12 14v3" />
                    </svg>
                  </div>
                  <div className="login-role-details">
                    <div className="login-role-title-row">
                      <span className="login-role-title">{t('system_admin')}</span>
                      <span className="login-role-tag">Admin</span>
                    </div>
                    <p className="login-role-desc">{t('role_card_admin_desc')}</p>
                  </div>
                  <svg className="login-role-arrow" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>

                <button
                  type="button"
                  className="login-role-choice role-investigator"
                  onClick={() => handleSelectRole('investigator')}
                >
                  <div className="login-role-icon-box">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                      <path d="M11 8v6M8 11h6" />
                    </svg>
                  </div>
                  <div className="login-role-details">
                    <div className="login-role-title-row">
                      <span className="login-role-title">{t('investigator')}</span>
                      <span className="login-role-tag">Investigator</span>
                    </div>
                    <p className="login-role-desc">{t('role_card_investigator_desc')}</p>
                  </div>
                  <svg className="login-role-arrow" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>
              </div>
            </div>
          ) : (
            /* STEP 2: Login Form for Selected Role */
            <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div className="login-active-role-bar">
                <div className="login-active-role-left">
                  <div className={`login-active-role-indicator role-${selectedRole}`} />
                  <span className="login-active-role-text">
                    {selectedRole === 'admin' ? t('system_admin') : t('investigator')}
                  </span>
                </div>
                <button
                  type="button"
                  className="login-change-role-btn"
                  onClick={handleResetRole}
                  title={t('change_role')}
                >
                  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="19" y1="12" x2="5" y2="12" />
                    <polyline points="12 19 5 12 12 5" />
                  </svg>
                  {t('change_role')}
                </button>
              </div>

              <label>{t('username')}</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={t('enter_username')}
                autoFocus
              />

              <label>{t('password')}</label>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('enter_password')}
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? t('hide_password') : t('show_password')}
                  aria-label={showPassword ? t('hide_password') : t('show_password')}
                >
                  {showPassword ? (
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                      <line x1="1" y1="1" x2="23" y2="23" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>

              <div className="login-options-row">
                <label className="show-password-label">
                  <input
                    type="checkbox"
                    checked={showPassword}
                    onChange={(e) => setShowPassword(e.target.checked)}
                  />
                  <span>{t('show_password')}</span>
                </label>
              </div>

              {error && <div className="error-box">{error}</div>}

              <button className="btn btn-primary" disabled={loading}>
                {loading
                  ? t('signing_in')
                  : selectedRole === 'admin'
                    ? t('select_role_admin')
                    : t('select_role_investigator')}
              </button>

              <div className="login-hint muted">
                {selectedRole === 'investigator'
                  ? t('login_hint_investigator')
                  : t('login_hint_admin')}
              </div>
            </form>
          )}
        </div>

        {/* DEMO LOGIN SECTION */}
        <div className="login-demo-section">
          <div className="login-demo-head">
            <svg className="login-demo-head-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 2l-2 2m-1.5 6.1L19 8l-4-4-1.9 1.5" />
              <path d="M15.5 8.5L7 17l-4 4 1-5 8.5-8.5" />
              <circle cx="17.5" cy="6.5" r="2.5" />
            </svg>
            <span className="login-demo-head-title">{t('demo_credentials_title')}</span>
          </div>
          <p className="login-demo-subtitle">{t('demo_credentials_subtitle')}</p>

          <div className="login-demo-grid">
            {/* System Admin Demo */}
            <div className="login-demo-card">
              <div className="login-demo-role-name role-admin">
                <span>{t('system_admin')}</span>
                <span className="login-role-tag">admin</span>
              </div>
              <div className="login-demo-creds">
                <div className="login-demo-cred-row">
                  <span className="login-demo-cred-label">{t('username')}:</span>
                  <code>admin</code>
                </div>
                <div className="login-demo-cred-row">
                  <span className="login-demo-cred-label">{t('password')}:</span>
                  <code>admin123</code>
                </div>
              </div>
              <button
                type="button"
                className="login-demo-autofill-btn"
                onClick={() => handleAutofill('admin', 'admin', 'admin123')}
                title={`${t('demo_autofill')} - ${t('system_admin')}`}
              >
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                {t('demo_autofill')}
              </button>
            </div>

            {/* Investigator Demo */}
            <div className="login-demo-card">
              <div className="login-demo-role-name role-investigator">
                <span>{t('investigator')}</span>
                <span className="login-role-tag">investigator</span>
              </div>
              <div className="login-demo-creds">
                <div className="login-demo-cred-row">
                  <span className="login-demo-cred-label">{t('username')}:</span>
                  <code>investigator1</code>
                </div>
                <div className="login-demo-cred-row">
                  <span className="login-demo-cred-label">{t('password')}:</span>
                  <code>investor1</code>
                </div>
              </div>
              <button
                type="button"
                className="login-demo-autofill-btn"
                onClick={() => handleAutofill('investigator', 'investigator1', 'investor1')}
                title={`${t('demo_autofill')} - ${t('investigator')}`}
              >
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                {t('demo_autofill')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
