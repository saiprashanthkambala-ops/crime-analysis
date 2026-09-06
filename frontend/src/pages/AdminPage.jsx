import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'

export default function AdminPage() {
  const [logs, setLogs] = useState(null)
  const [users, setUsers] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    Promise.all([api('/audit'), api('/admin/users')])
      .then(([l, u]) => { setLogs(l); setUsers(u) })
      .catch((e) => setErr(e.message))
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!logs || !users) return <Spinner />

  return (
    <div className="page">
      <h2>Administration</h2>

      <div className="two-col">
        <Panel title={`Audit Trail (${logs.length})`}>
          {logs.length === 0 && <Empty message="No audit events." />}
          <table className="table">
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="mono small">{l.created_at ? new Date(l.created_at).toLocaleString() : ''}</td>
                  <td>{l.user}</td>
                  <td>{l.action}</td>
                  <td className="mono small">{l.entity_type} {l.entity_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

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
      </div>
    </div>
  )
}
