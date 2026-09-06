import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'

export default function AdminPage() {
  const [logs, setLogs] = useState(null)
  const [users, setUsers] = useState(null)
  const [cases, setCases] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const [nu, setNu] = useState({ username: '', password: '', full_name: '', email: '', role: 'investigator' })

  const load = () =>
    Promise.all([api('/audit'), api('/admin/users'), api('/admin/cases')])
      .then(([l, u, c]) => { setLogs(l); setUsers(u); setCases(c) })
      .catch((e) => setErr(e.message))

  useEffect(() => { load() }, [])

  const createUser = async (e) => {
    e.preventDefault()
    if (!nu.username || !nu.password) return
    try {
      await api('/admin/users', { method: 'POST', body: JSON.stringify(nu) })
      setNu({ username: '', password: '', full_name: '', email: '', role: 'investigator' })
      setMsg('User created.')
      await load()
    } catch (err) { setErr(err.message) }
  }

  const assign = async (caseId, userId, action) => {
    try {
      await api(`/admin/cases/${caseId}/users`, {
        method: 'POST', body: JSON.stringify({ user_id: userId, action }),
      })
      await load()
    } catch (err) { setErr(err.message) }
  }

  if (err) return <ErrorBox message={err} />
  if (!logs || !users || !cases) return <Spinner />

  return (
    <div className="page">
      <h2>Administration</h2>
      {msg && <div className="info-box">{msg}</div>}

      <div className="two-col">
        <Panel title={`Audit Trail (${logs.length})`}>
          {logs.length === 0 && <Empty message="No audit events." />}
          <table className="table">
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th></tr></thead>
            <tbody>
              {logs.slice(0, 100).map((l) => (
                <tr key={l.id}>
                  <td className="mono small">{l.created_at ? new Date(l.created_at).toLocaleString() : ''}</td>
                  <td>{l.user || 'system'}</td>
                  <td>{l.action}</td>
                  <td className="mono small">{l.entity_type} {l.entity_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Panel title={`Users (${users.length})`}>
            <table className="table">
              <thead><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Active</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.full_name}</td>
                    <td><span className="badge role-badge">{u.role}</span></td>
                    <td>{u.is_active ? '✓' : '✕'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Create User">
            <form onSubmit={createUser} className="form">
              <input placeholder="Username" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
              <input type="password" placeholder="Password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
              <input placeholder="Full name" value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
              <input placeholder="Email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
              <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
                <option value="investigator">investigator</option>
                <option value="admin">admin</option>
              </select>
              <button className="btn btn-primary">Create User</button>
            </form>
          </Panel>
        </div>
      </div>

      <Panel title="Case Access">
        <table className="table">
          <thead><tr><th>Case</th><th>Assigned Investigators</th></tr></thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id}>
                <td><b>{c.name}</b> <span className="muted mono">({c.id})</span></td>
                <td>
                  {users.map((u) => {
                    const on = c.assigned.includes(u.id)
                    return (
                      <button
                        key={u.id}
                        className={`btn btn-ghost small`}
                        style={{ marginRight: 4, background: on ? 'rgba(34,211,238,0.15)' : undefined }}
                        onClick={() => assign(c.id, u.id, on ? 'remove' : 'add')}
                        title={on ? 'Click to remove access' : 'Click to grant access'}
                      >
                        {on ? '✓' : ''} {u.username}
                      </button>
                    )
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
