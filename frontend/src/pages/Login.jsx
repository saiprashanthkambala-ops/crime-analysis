import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth'
import { ThemeToggle } from '../components/ui'
import appLogo from '../profil icon'

export default function Login() {
  const { login, logout } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedRole = searchParams.get('role')
  const roleLabel = requestedRole === 'admin' ? 'System Admin' : requestedRole === 'investigator' ? 'Investigator' : ''
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const signedInUser = await login(username, password)
      if (requestedRole && signedInUser.role !== requestedRole) {
        await logout()
        throw new Error(
          requestedRole === 'investigator'
            ? 'This account is not an investigator account. Sign in with an assigned investigator account.'
            : 'This account is not a system admin account. Sign in with the system admin account.'
        )
      }
      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-top-bar">
        <ThemeToggle />
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="login-logo-container">
            <img src={appLogo} alt="Crime Analysis" className="login-logo-img" />
          </div>
          <h1>Crime Analysis</h1>
          <p className="muted">AI-Assisted Criminal Network Analysis</p>
          {roleLabel && <div className="login-role-context">{roleLabel} sign in</div>}
        </div>
        <label>Username</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Enter username"
          autoFocus
        />
        <label>Password</label>
        <div className="password-input-wrap">
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
          />
          <button
            type="button"
            className="password-toggle-btn"
            onClick={() => setShowPassword(!showPassword)}
            title={showPassword ? 'Hide password' : 'Show password'}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
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
            <span>Show password</span>
          </label>
        </div>
        {error && <div className="error-box">{error}</div>}
        <button className="btn btn-primary" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
        <div className="login-hint muted">
          {requestedRole === 'investigator'
            ? <>Investigator access uses an assigned investigator account.</>
            : requestedRole === 'admin'
              ? <>System Admin access requires the administrator account.</>
              : <>Demo: <code>investigator1 / investor1</code> · <code>admin / admin123</code></>}
        </div>
      </form>
    </div>
  )
}
