import { createContext, useContext, useEffect, useState } from 'react'
import { api, clearToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('crime_analysis_user')) } catch { return null }
  })
  const [sessionChecked, setSessionChecked] = useState(false)

  useEffect(() => {
    let active = true
    api('/auth/me')
      .then((currentUser) => {
        if (!active) return
        localStorage.setItem('crime_analysis_user', JSON.stringify(currentUser))
        setUser(currentUser)
      })
      .catch(() => {
        if (!active) return
        clearToken()
        setUser(null)
      })
      .finally(() => {
        if (active) setSessionChecked(true)
      })
    return () => { active = false }
  }, [])

  const login = async (username, password) => {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    localStorage.setItem('crime_analysis_user', JSON.stringify(data.user))
    setUser(data.user)
    return data.user
  }

  const logout = async () => {
    try { await api('/auth/logout', { method: 'POST' }) } catch (_) {}
    clearToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthed: sessionChecked && !!user, sessionChecked }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
