import { createContext, useContext, useState } from 'react'
import { api, setToken, clearToken, getToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('crime_analysis_user')) } catch { return null }
  })

  const login = async (username, password) => {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setToken(data.access_token)
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
    <AuthContext.Provider value={{ user, login, logout, isAuthed: !!getToken() }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
