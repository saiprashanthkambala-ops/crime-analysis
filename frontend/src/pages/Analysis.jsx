import { useEffect, useMemo, useState } from 'react'
import { api, streamAnalysisChat } from '../api'
import { ErrorBox, Panel, Spinner, StatCard } from '../components/ui'
import NetworkGraph from '../components/NetworkGraph'
import MarkdownMessage from '../components/MarkdownMessage'

const REQUEST_TIMEOUT_MS = 50000

async function withTimeout(path, options = {}) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    return await api(path, { ...options, signal: controller.signal })
  } finally {
    window.clearTimeout(timer)
  }
}

export default function Analysis() {
  const [cases, setCases] = useState([])
  const [selected, setSelected] = useState([])
  const [analysis, setAnalysis] = useState('')
  const [context, setContext] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [syncStatus, setSyncStatus] = useState(null)
  const [graphStatus, setGraphStatus] = useState('not_loaded')
  const [nvidiaReady, setNvidiaReady] = useState(null)
  const [graphAnalysis, setGraphAnalysis] = useState(null)
  const [graphAnalysisLoading, setGraphAnalysisLoading] = useState(false)
  const [graphAnalysisCaseId, setGraphAnalysisCaseId] = useState('')
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  const [chatting, setChatting] = useState(false)
  const [err, setErr] = useState('')
  const [agentTools, setAgentTools] = useState({})
  const [suspicious, setSuspicious] = useState([])

  useEffect(() => {
    Promise.all([
      api('/cases'),
      api('/analysis/nvidia-status'),
    ])
      .then(([items, status]) => {
        setCases(items)
        setNvidiaReady(status)
        if (items.length === 1) {
          setSelected([items[0].id])
          void refreshSyncStatus(items[0].id)
        }
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  const selectedCases = useMemo(
    () => cases.filter((c) => selected.includes(c.id)),
    [cases, selected]
  )

  const toggleCase = (id) => {
    setSelected((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
      if (!next.includes(graphAnalysisCaseId)) setGraphAnalysisCaseId(next[0] || '')
      return next
    })
    setGraphAnalysis(null)
    void refreshSyncStatus(selected.includes(id) ? '' : id)
  }

  const refreshSuspicious = async () => {
    if (!selected.length) {
      setSuspicious([])
      return
    }
    try {
      const data = await withTimeout(
        '/analysis/suspicious?case_ids=' + encodeURIComponent(selected.join(','))
      )
      setSuspicious(data.candidates || [])
    } catch (e) {
      if (e.name !== 'AbortError') setErr(e.message)
    }
  }

  const generateGraph = async () => {
    if (!selected.length) {
      setErr('Select at least one case before generating the graph.')
      return
    }
    setErr('')
    setGraphStatus('generating')
    try {
      const data = await withTimeout('/graph/generate', {
        method: 'POST',
        body: JSON.stringify({ case_ids: selected }),
      })
      setGraph(data)
      setGraphStatus(data.source || 'generated')
    } catch (e) {
      setGraph({ nodes: [], edges: [] })
      setGraphStatus('unavailable')
      setErr(
        e.name === 'AbortError'
          ? 'Graph generation timed out. Check Neo4j connectivity and the selected case data.'
          : e.message
      )
    }
  }

  const refreshSyncStatus = async (caseId = '') => {
    const id = caseId || selected[0] || ''
    if (!id) {
      setSyncStatus(null)
      return
    }
    try {
      const data = await withTimeout('/graph/sync-status/' + encodeURIComponent(id))
      setSyncStatus(data)
    } catch (e) {
      if (e.name !== 'AbortError') setErr(e.message)
    }
  }

  const resyncCase = async () => {
    const id = graphAnalysisCaseId || selected[0] || ''
    if (!id) return
    setErr('')
    try {
      await withTimeout('/graph/sync/' + encodeURIComponent(id), { method: 'POST' })
      await refreshSyncStatus(id)
      await refreshGraph()
      await runGraphAnalysis(id)
    } catch (e) {
      setErr(e.message)
    }
  }

  const refreshGraph = async () => {
    if (!selected.length) {
      setGraph({ nodes: [], edges: [] })
      setGraphStatus('not_loaded')
      return
    }
    try {
      const data = await withTimeout(
        '/analysis/graph?case_ids=' + encodeURIComponent(selected.join(','))
      )
      setGraph(data.graph || { nodes: [], edges: [] })
      setGraphStatus(data.graph_status || data.source || 'unknown')
    } catch (e) {
      setGraph({ nodes: [], edges: [] })
      setGraphStatus('unavailable')
      if (e.name !== 'AbortError') setErr(e.message)
    }
  }

  const runAnalysis = async () => {
    setErr('')
    setGenerating(true)

    try {
      const data = await withTimeout('/analysis/generate', {
        method: 'POST',
        body: JSON.stringify({ case_ids: selected }),
      })

      setAnalysis(data.analysis || '')
      setContext(data.context || null)
      void refreshSuspicious()
      const firstGraphCase = graphAnalysisCaseId || selected[0] || ''
      if (firstGraphCase) {
        setGraphAnalysisCaseId(firstGraphCase)
        setGraphAnalysisLoading(true)
        void withTimeout('/graph-analysis?case_ids=' + encodeURIComponent(firstGraphCase))
          .then((graphData) => setGraphAnalysis(graphData))
          .catch((graphError) => {
            if (graphError.name !== 'AbortError') {
              setErr('AI analysis succeeded, but graph analysis could not be loaded: ' + graphError.message)
            }
          })
          .finally(() => setGraphAnalysisLoading(false))
      }
      // Generate the selected-case graph explicitly after AI analysis.
      void generateGraph()
    } catch (e) {
      setErr(
        e.name === 'AbortError'
          ? 'Analysis timed out after 50 seconds. Check NVIDIA_API_KEY and the backend server log.'
          : e.message
      )
    } finally {
      setGenerating(false)
    }
  }

  const runGraphAnalysis = async (requestedCaseId = '') => {
    const caseId = requestedCaseId || graphAnalysisCaseId || selected[0] || ''
    if (!caseId) {
      setErr('Select a case to run graph analysis.')
      return
    }
    setErr('')
    setGraphAnalysisLoading(true)
    try {
      const data = await withTimeout('/graph-analysis?case_ids=' + encodeURIComponent(caseId))
      setGraphAnalysis(data)
    } catch (e) {
      setErr(
        e.name === 'AbortError'
          ? 'Graph analysis timed out. Check Neo4j and Neo4j Graph Data Science (GDS).'
          : e.message
      )
    } finally {
      setGraphAnalysisLoading(false)
    }
  }

  const sendMessage = async (e) => {
    e.preventDefault()

    const text = message.trim()
    if (!text || chatting) return

    setMessage('')
    setErr('')
    const messageIndex = messages.length
    setMessages((prev) => [
      ...prev,
      { role: 'investigator', content: text },
      { role: 'assistant', content: '' },
    ])
    setChatting(true)

    const history = messages
      .slice(-6)
      .map((m) => ({
        role: m.role === 'investigator' ? 'user' : 'assistant',
        content: m.content || '',
      }))
      .filter((m) => m.content)

    try {
      const data = await streamAnalysisChat(
        selected,
        text,
        (token) => {
          setMessages((prev) =>
            prev.map((m, i) =>
              i === messageIndex + 1
                ? { ...m, content: (m.content || '') + token }
                : m
            )
          )
        },
        { timeoutMs: 90000 }
      )

      if (data.context) setContext(data.context)
      setAgentTools((prev) => ({ ...prev, [messageIndex + 1]: data.tool || data.mode || 'case_context' }))
      void generateGraph()
      void refreshSuspicious()
    } catch (e) {
      const detail = e.name === 'AbortError'
        ? 'Chat timed out after 90 seconds. Check NVIDIA_API_KEY, NVIDIA connectivity, and the backend log.'
        : e.message
      setErr(detail)
      setMessages((prev) =>
        prev.map((m, i) =>
          i === messageIndex + 1
            ? { ...m, content: 'Request failed: ' + detail }
            : m
        )
      )
    } finally {
      setChatting(false)
    }
  }

  if (loading) return <Spinner label="Loading cases…" />

  return (
    <div className="page analysis-page">
      <div>
        <h2>Analysis</h2>
        <p className="muted">
          Case-level analysis and an evidence-grounded investigation assistant.
        </p>
      </div>

      {err && <ErrorBox message={err} />}

      {nvidiaReady && (
        <div className={nvidiaReady.configured ? 'info-box' : 'error-box'}>
          {nvidiaReady.configured
            ? 'NVIDIA Nemotron is configured on the backend.'
            : 'NVIDIA API key is missing on the backend. Add NVIDIA_API_KEY to .env and restart the backend.'}
        </div>
      )}

      <Panel
        title="Cases for Analysis"
        className="analysis-blue-panel"
        actions={
          <span className="muted small">
            {selected.length} selected
          </span>
        }
      >
        {cases.length === 0 ? (
          <div className="empty muted">
            No authorized cases are available.
          </div>
        ) : (
          <div className="analysis-case-picker">
            {cases.map((c) => (
              <label key={c.id} className={'analysis-case-card' + (selected.includes(c.id) ? ' is-selected' : '')}>
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  onChange={() => toggleCase(c.id)}
                />
                <span className="analysis-case-info">
                  <strong>{c.name}</strong>
                  <span className="muted small mono">{c.id}</span>
                </span>
                <span className="badge status-badge">{c.status}</span>
              </label>
            ))}
          </div>
        )}

        {syncStatus && (
          <div className="info-box small">
            Neo4j sync: <strong>{syncStatus.status}</strong>
            {syncStatus.synced_at ? ` · Last sync: ${new Date(syncStatus.synced_at).toLocaleString()}` : ''}
            {syncStatus.error ? ` · ${syncStatus.error}` : ''}
            {syncStatus.status !== 'SYNCED' && (
              <button className="btn" type="button" onClick={resyncCase} style={{ marginLeft: 8 }}>
                Sync Case to Neo4j
              </button>
            )}
          </div>
        )}

        <div className="analysis-actions">
          <button
            className="btn btn-primary"
            disabled={
              !selected.length ||
              generating ||
              nvidiaReady?.configured === false
            }
            onClick={runAnalysis}
          >
            {generating ? 'Generating…' : 'Generate Analysis'}
          </button>
          <button
            className="btn"
            disabled={!selected.length || graphStatus === 'generating'}
            onClick={generateGraph}
          >
            {graphStatus === 'generating' ? 'Generating Graph…' : 'Generate Graph'}
          </button>

          {selected.length > 1 && (
            <select
              className="select-inline"
              value={graphAnalysisCaseId || selected[0] || ''}
              onChange={(e) => {
                setGraphAnalysisCaseId(e.target.value)
                setGraphAnalysis(null)
              }}
            >
              {selected.map((caseId) => (
                <option key={caseId} value={caseId}>
                  Graph metrics: {caseId}
                </option>
              ))}
            </select>
          )}
          <button
            className="btn"
            disabled={!selected.length || graphAnalysisLoading}
            onClick={() => runGraphAnalysis()}
          >
            {graphAnalysisLoading ? 'Running Graph Analysis…' : 'Run Graph Analysis'}
          </button>

          {selectedCases.length > 0 && (
            <span className="muted small">
              Analyzing: {selectedCases.map((c) => c.name).join(', ')}
            </span>
          )}
        </div>
      </Panel>

      {context && (
        <div className="stat-grid">
          <StatCard label="Cases" value={context.counts?.cases ?? 0} />
          <StatCard label="People" value={context.counts?.people ?? 0} />
          <StatCard label="Entities" value={context.counts?.entities ?? 0} />
          <StatCard
            label="Relationships"
            value={context.counts?.relationships ?? 0}
          />
          <StatCard label="Evidence" value={context.counts?.evidence ?? 0} />
        </div>
      )}

      {graphAnalysis && (
        <Panel
          title="Graph Analysis"
          actions={
            <span className="muted small">
              {graphAnalysis.engine || 'graph-engine'} · {graphAnalysis.entity_count} people · {graphAnalysis.edge_count ?? 0} links
            </span>
          }
        >
          <div className="stat-grid">
            <StatCard
              label="Communities"
              value={Object.keys(graphAnalysis.community_sizes || {}).length}
            />
            <StatCard
              label="Components"
              value={new Set(
                (graphAnalysis.metrics?.connected_components || []).map((x) => x.componentId)
              ).size}
            />
            <StatCard
              label="Top PageRank"
              value={
                graphAnalysis.ranked_people?.[0]?.pagerank != null
                  ? graphAnalysis.ranked_people[0].pagerank.toFixed(4)
                  : '—'
              }
            />
            <StatCard
              label="Top Degree"
              value={
                graphAnalysis.ranked_people?.[0]?.degree != null
                  ? graphAnalysis.ranked_people[0].degree.toFixed(2)
                  : '—'
              }
            />
          </div>

          <div className="info-box small">
            Engine: {graphAnalysis.engine || 'local graph engine'}. Betweenness: {graphAnalysis.betweenness_mode || 'exact'}.
            These values describe network structure and evidence-backed connectivity; they are not probabilities of guilt.
          </div>

          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Entity</th>
                  <th>Degree</th>
                  <th>Betweenness</th>
                  <th>PageRank</th>
                  <th>Closeness</th>
                  <th>Community</th>
                </tr>
              </thead>
              <tbody>
                {(graphAnalysis.ranked_people || []).slice(0, 20).map((r) => (
                  <tr key={r.entity_id}>
                    <td>
                      <strong>{r.name || r.entity_id}</strong>
                      <span className="muted small mono">{r.entity_id}</span>
                    </td>
                    <td className="mono">{Number(r.degree).toFixed(6)}</td>
                    <td className="mono">{Number(r.betweenness).toFixed(6)}</td>
                    <td className="mono">{Number(r.pagerank).toFixed(6)}</td>
                    <td className="mono">{Number(r.closeness).toFixed(6)}</td>
                    <td className="mono">{r.community_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="two-col">
            <Panel title="Communities — Louvain">
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th>Entity</th><th>Community</th></tr></thead>
                  <tbody>
                    {(graphAnalysis.metrics?.louvain_communities || []).slice(0, 25).map((r) => (
                      <tr key={r.entity_id}>
                        <td>{r.name || r.entity_id}</td>
                        <td className="mono">{r.communityId}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Connected Components">
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th>Entity</th><th>Component</th></tr></thead>
                  <tbody>
                    {(graphAnalysis.metrics?.connected_components || []).slice(0, 25).map((r) => (
                      <tr key={r.entity_id}>
                        <td>{r.name || r.entity_id}</td>
                        <td className="mono">{r.componentId}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>

          <Panel title="Top Similar Entity Pairs">
            <div className="table-scroll">
              <table className="table">
                <thead><tr><th>Entity A</th><th>Entity B</th><th>Jaccard</th></tr></thead>
                <tbody>
                  {(graphAnalysis.metrics?.node_similarity || []).slice(0, 15).map((r, i) => (
                    <tr key={r.entity_a + '-' + r.entity_b + '-' + i}>
                      <td>{r.name_a || r.entity_a}</td>
                      <td>{r.name_b || r.entity_b}</td>
                      <td className="mono">{Number(r.similarity).toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Temporal Overview">
            <div className="stat-grid">
              <StatCard label="Events" value={graphAnalysis.temporal?.event_count ?? 0} />
              <StatCard label="Timed Events" value={graphAnalysis.temporal?.timed_event_count ?? 0} />
            </div>
          </Panel>
        </Panel>
      )}

      <div className="two-col analysis-workspace">
        <Panel title="Suspicious Relationship Candidates" className="analysis-blue-panel">
        {suspicious.length ? (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Person A</th>
                  <th>Person B</th>
                  <th>Score</th>
                  <th>Strength</th>
                  <th>Signals</th>
                </tr>
              </thead>
              <tbody>
                {suspicious.slice(0, 15).map((r) => (
                  <tr key={r.id}>
                    <td>{r.person_a?.name || r.person_a?.id}</td>
                    <td>{r.person_b?.name || r.person_b?.id}</td>
                    <td className="mono">{r.score ?? '—'}</td>
                    <td><span className="badge status-badge">{r.strength || '—'}</span></td>
                    <td className="muted small">
                      {Object.entries(r.signals || {})
                        .filter(([, v]) => Array.isArray(v) ? v.length : v)
                        .map(([k, v]) => k + ': ' + (Array.isArray(v) ? v.length : v))
                        .join(' · ') || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty muted">No relationship candidates are currently ranked for the selected case set.</div>
        )}
        <div className="info-box small">
          Candidates are prioritized from stored relationship-strength signals. They are investigation leads, not guilt determinations.
        </div>
      </Panel>

        <Panel title="Generated Case Analysis" className="glass-panel analysis-summary-panel analysis-blue-panel">
          {analysis ? (
            <div className="analysis-summary-content">
              <MarkdownMessage text={analysis} />
            </div>
          ) : (
            <div className="empty muted">
              Select one or more cases and generate an analysis.
            </div>
          )}
        </Panel>

        <Panel title="Investigation Assistant" className="glass-panel chat-panel analysis-blue-panel">
          <div className="chat-shell">
            <div className="chat-messages">
              {messages.length === 0 && (
                <div className="empty muted">
                  Ask about relationships, evidence, connected people, or case
                  patterns.
                </div>
              )}

              {messages.map((m, i) => (
                <div
                  key={i}
                  className={'chat-message chat-' + m.role}
                >
                  <div className="chat-role">
                    {m.role === 'investigator'
                      ? 'Investigator'
                      : 'Nemotron'}
                  </div>
                  <div className="chat-content">{m.role === 'assistant' ? <MarkdownMessage text={m.content} /> : m.content}</div>
                  {m.role === 'assistant' && agentTools[i] && (
                    <div className="chat-tool-tag">Analysis tool: {agentTools[i]}</div>
                  )}
                </div>
              ))}

              {chatting && (
                <div className="chat-message chat-assistant chat-thinking">
                  <div className="chat-role">Nemotron</div>
                  <div className="chat-content muted">
                    <span className="thinking-dot"></span> Thinking…
                  </div>
                </div>
              )}
            </div>

            <form className="chat-form" onSubmit={sendMessage}>
              <div className="chat-input-wrapper">
                <input
                  type="text"
                  className="chat-input"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      if (message.trim() && selected.length && !chatting && nvidiaReady?.configured !== false) {
                        sendMessage(e)
                      }
                    }
                  }}
                  placeholder="Ask a question about the selected case(s)… (Press Enter to send)"
                  disabled={!selected.length || chatting}
                  autoComplete="off"
                />

                <button
                  type="submit"
                  className="chat-send-btn"
                  disabled={
                    !selected.length ||
                    chatting ||
                    !message.trim() ||
                    nvidiaReady?.configured === false
                  }
                  title="Send message (Enter)"
                  aria-label="Send message"
                >
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                  </svg>
                  <span>Send</span>
                </button>
              </div>
            </form>
          </div>
        </Panel>
      </div>

      <Panel
        title="Relevant Graph"
        className="analysis-blue-panel"
        actions={
          graphStatus !== 'not_loaded' ? (
            <span className="muted small">
              Source: {graphStatus === 'neo4j' ? 'Neo4j' : graphStatus === 'sql-fallback' ? 'SQL fallback' : graphStatus}
            </span>
          ) : null
        }
      >
        {graph.nodes?.length ? (
          <NetworkGraph data={graph} onSelectNode={() => {}} />
        ) : (
          <div className="empty muted">
            Select the cases above and click Generate Graph.
          </div>
        )}
      </Panel>

      {context?.relationships?.length > 0 && (
        <Panel title="Top Evidence-Backed Relationships">
          <table className="table">
            <thead>
              <tr>
                <th>Person A</th>
                <th>Person B</th>
                <th>Strength</th>
                <th>Score</th>
                <th>Signals</th>
              </tr>
            </thead>

            <tbody>
              {context.relationships.slice(0, 20).map((r) => (
                <tr key={r.id}>
                  <td>{r.person_a?.name}</td>
                  <td>{r.person_b?.name}</td>
                  <td>
                    <span className="badge status-badge">
                      {r.strength}
                    </span>
                  </td>
                  <td className="mono">{r.score ?? '—'}</td>
                  <td className="muted small">
                    {Object.entries(r.signals || {})
                      .filter(([, v]) =>
                        Array.isArray(v) ? v.length : v
                      )
                      .map(
                        ([k, v]) =>
                          k + ': ' + (Array.isArray(v) ? v.length : v)
                      )
                      .join(' · ') || '—'}
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
