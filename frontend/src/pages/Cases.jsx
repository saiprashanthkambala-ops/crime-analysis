import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'

export default function Cases() {
  const [cases, setCases] = useState(null)
  const [err, setErr] = useState('')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [creating, setCreating] = useState(false)

  const load = () => api('/cases').then(setCases).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])

  const create = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      await api('/cases', { method: 'POST', body: JSON.stringify({ name, description: desc }) })
      setName(''); setDesc('')
      await load()
    } catch (err) { setErr(err.message) } finally { setCreating(false) }
  }

  if (err) return <ErrorBox message={err} />
  if (!cases) return <Spinner />

  return (
    <div className="page">
      <h2>Cases</h2>
      <div className="two-col">
        <Panel title="Case List">
          <table className="table">
            <thead>
              <tr><th>ID</th><th>Name</th><th>Status</th><th>Documents</th></tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.id}</td>
                  <td><Link className="link" to={`/cases/${c.id}`}>{c.name}</Link></td>
                  <td><span className="badge status-badge">{c.status}</span></td>
                  <td className="muted">{c.documents.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Create Case">
          <form onSubmit={create} className="form">
            <label>Case Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} />
            <label>Description</label>
            <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={4} />
            <button className="btn btn-primary" disabled={creating}>
              {creating ? 'Creating…' : 'Create Case'}
            </button>
          </form>
        </Panel>
      </div>
    </div>
  )
}
