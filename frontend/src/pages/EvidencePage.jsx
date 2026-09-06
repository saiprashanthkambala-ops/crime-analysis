import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'

export default function EvidencePage() {
  const [evidence, setEvidence] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => { api('/evidence').then(setEvidence).catch((e) => setErr(e.message)) }, [])

  if (err) return <ErrorBox message={err} />
  if (!evidence) return <Spinner />

  return (
    <div className="page">
      <h2>Evidence</h2>
      <p className="muted">Every record is traceable to its source. {evidence.length} records.</p>
      <Panel title="Evidence Records">
        <table className="table">
          <thead>
            <tr><th>ID</th><th>Type</th><th>Person A</th><th>Person B</th><th>Source</th><th>Date</th><th>Time</th><th>Confidence</th></tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.id}</td>
                <td className="muted">{e.type}</td>
                <td className="mono">{e.person_a}</td>
                <td className="mono">{e.person_b}</td>
                <td className="mono">{e.source}</td>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">Unavailable</span>}</td>
                <td className="mono">{e.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
