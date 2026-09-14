import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ErrorBox, Panel, Spinner, StatCard } from '../components/ui'
import NetworkGraph from '../components/NetworkGraph'

const REQUEST_TIMEOUT_MS = 95000

function timeoutSignal() {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  return { controller, timer }
}

export default function Analysis() {
  const [cases, setCases] = useState([])
  const [selected, setSelected] = useState([])
  const [analysis, setAnalysis] = useState('')
  const [context, setContext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  const [chatting, setChatting] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/cases')
      .then((items) => {
        setCases(items)
        if (items.length === 1) setSelected([items[0].id])
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  const toggleCase = (id) => {
    setSelected((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }

  const selectedCases = useMemo(() => cases.filter((c) => selected.includes(c.id)), [cases, selected])

  const runAnalysis = async () => {
    setErr('')
    setGenerating(true)
    const { controller, timer } = timeoutSignal()
    try {
      const data = await api('/analysis/generate', {
        method: 'POST',
        body: JSON.stringify({ case_ids: selected }),
        signal: controller.signal,
      })
      setAnalysis(data.analysis || '')
      setContext(data.context || null)
    } catch (e) {
      if (e.name === 'AbortError') {
        setErr('Analysis request timed out. Check the NVIDIA API key, backend logs, Neo4j connection, and network access.')
      } else {
        setErr(e.message)
      }
    } finally {
      window.clearTimeout(timer)
      setGenerating(false)
    }
  }

  const sendMessage = async (e) => {
    e.preventDefault()
    const text = message.trim()
    if (!text || chatting) return
    setMessage('')
    setErr('')
    setMessages((prev) => [...prev, { role: 'investigator', content: text }])
    setChatting(true)
    const { controller, timer } = timeoutSignal()
    try {
      const data = await api('/analysis/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, case_ids: selected }),
        signal: controller.signal,
      })
      setContext(data.context || null)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer || 'No answer returned.' }])
    } catch (e2) {
      const detail = e2.name === 'AbortError'
        ? 'Chat request timed out. Check the NVIDIA API key, backend logs, Neo4j connection, and network access.'
        : e2.message
      setErr(detail)
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Request failed: ' + detail }])
    } finally {
      window.clearTimeout(timer)
      setChatting(false)
    }
  }

  if (loading) return <Spinner label="Loading cases…" />

  const graph = context?.graph || { nodes: [], edges: [] }

  return (
    <div className="page analysis-page">
      <div>
        <h2>Analysis</h2>
        <p className="muted">Case-level relationship analysis and an evidence-grounded investigation assistant.</p>
      </div>

      {err && <ErrorBox message={err} />}

      <Panel title="Cases for Analysis" actions={<span className="muted small">{selected.length} selected</span>}>
        {cases.length === 0 ? (
          <div className="empty muted">No authorized cases are available.</div>
        ) : (
          <div className="analysis-case-picker">
            {cases.map((c) => (
              <label key={c.id} className="analysis-case-card">
                <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleCase(c.id)} />
                <span className="analysis-case-info">
                  <strong>{c.name}</strong>
                  <span className="muted small mono">{c.id}</span>
                </span>
                <span className="badge status-badge">{c.status}</span>
              </label>
            ))}
          </div>
        )}
        <div className="analysis-actions">
          <button className="btn btn-primary" disabled={!selected.length || generating} onClick={runAnalysis}>
            {generating ? 'Generating…' : 'Generate Analysis'}
          </button>
          {selectedCases.length > 0 && <span className="muted small">Analyzing: {selectedCases.map((c) => c.name).join(', ')}</span>}
        </div>
      </Panel>

      {context && (
        <div className="stat-grid">
          <StatCard label="Cases" value={context.counts?.cases ?? 0} />
          <StatCard label="People" value={context.counts?.people ?? 0} />
          <StatCard label="Entities" value={context.counts?.entities ?? 0} />
          <StatCard label="Relationships" value={context.counts?.relationships ?? 0} />
          <StatCard label="Evidence" value={context.counts?.evidence ?? 0} />
        </div>
      )}

      <div className="two-col analysis-workspace">
        <Panel title="Generated Case Analysis">
          {analysis ? <div className="analysis-text">{analysis}</div> : <div className="empty muted">Select one or more cases and generate an analysis.</div>}
        </Panel>

        <Panel title="Investigation Chat">
          <div className="chat-shell">
            <div className="chat-messages">
              {messages.length === 0 && <div className="empty muted">Ask about relationships, evidence, connected people, or case patterns.</div>}
              {messages.map((m, i) => (
                <div key={i} className={'chat-message chat-' + m.role}>
                  <div className="chat-role">{m.role === 'investigator' ? 'Investigator' : 'Nemotron'}</div>
                  <div className="chat-content">{m.content}</div>
                </div>
              ))}
              {chatting && <div className="chat-message chat-assistant"><div className="chat-role">Nemotron</div><div className="chat-content muted">Thinking…</div></div>}
            </div>
            <form className="chat-form" onSubmit={sendMessage}>
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ask a question about the selected case(s)…" rows={3} disabled={!selected.length || chatting} />
              <button className="btn btn-primary" disabled={!selected.length || chatting || !message.trim()}>Send</button>
            </form>
          </div>
        </Panel>
      </div>

      <Panel title="Relevant Graph">
        {graph.nodes?.length ? <NetworkGraph data={graph} onSelectNode={() => {}} /> : <div className="empty muted">Generate analysis or ask a chat question to load the selected-case graph.</div>}
      </Panel>

      {context?.relationships?.length > 0 && (
        <Panel title="Top Evidence-Backed Relationships" actions={<span className="muted small">Top {Math.min(context.relationships.length, 100)}</span>}>
          <table className="table">
            <thead><tr><th>Person A</th><th>Person B</th><th>Strength</th><th>Score</th><th>Signals</th></tr></thead>
            <tbody>
              {context.relationships.slice(0, 20).map((r) => (
                <tr key={r.id}>
                  <td>{r.person_a?.name}</td>
                  <td>{r.person_b?.name}</td>
                  <td><span className="badge status-badge">{r.strength}</span></td>
                  <td className="mono">{r.score ?? '—'}</td>
                  <td className="muted small">
                    {Object.entries(r.signals || {}).filter(([, v]) => Array.isArray(v) ? v.length : v)
                      .map(([k, v]) => k + ': ' + (Array.isArray(v) ? v.length : v)).join(' · ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  )
}