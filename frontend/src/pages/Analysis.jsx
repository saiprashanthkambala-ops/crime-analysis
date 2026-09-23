import { useEffect, useMemo, useRef, useState } from 'react'
import { api, streamAnalysisChat } from '../api'
import { ErrorBox, Panel, Spinner, StatCard } from '../components/ui'
import NetworkGraph from '../components/NetworkGraph'
import MarkdownMessage from '../components/MarkdownMessage'
import { useI18n } from '../i18n'
import { useAnalysisRuntime } from '../analysisRuntime'

const REQUEST_TIMEOUT_MS = 300000

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
  const { t } = useI18n()
  const [cases, setCases] = useState([])
  const [nvidiaReady, setNvidiaReady] = useState(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [err, setErr] = useState('')
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [entityLoading, setEntityLoading] = useState(false)
  const analysisProgressTimer = useRef(null)
  const graphProgressTimer = useRef(null)

  const {
    selected, setSelected,
    analysis, setAnalysis,
    context, setContext,
    graph, setGraph,
    syncStatus, setSyncStatus,
    graphStatus, setGraphStatus,
    graphAnalysis, setGraphAnalysis,
    graphAnalysisLoading, setGraphAnalysisLoading,
    graphAnalysisCaseId, setGraphAnalysisCaseId,
    generating, setGenerating,
    messages, setMessages,
    chatting, setChatting,
    agentTools, setAgentTools,
    suspicious, setSuspicious,
    analysisProgress, setAnalysisProgress,
    graphProgress, setGraphProgress,
  } = useAnalysisRuntime()

  const startEstimatedProgress = (setter, timerRef) => {
    window.clearInterval(timerRef.current)
    setter(8)
    timerRef.current = window.setInterval(() => {
      setter((current) => current >= 92 ? current : Math.min(92, current + Math.max(1, Math.round((92 - current) / 7))))
    }, 900)
  }

  const finishProgress = (setter, timerRef) => {
    window.clearInterval(timerRef.current)
    timerRef.current = null
    setter(100)
  }

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
      setErr(t('err_select_case_graph'))
      return
    }
    setErr('')
    setGraphStatus('generating')
    startEstimatedProgress(setGraphProgress, graphProgressTimer)
    try {
      const data = await withTimeout('/graph/generate', {
        method: 'POST',
        body: JSON.stringify({ case_ids: selected }),
      })
      setGraph(data)
      setGraphStatus(data.source || 'generated')
      finishProgress(setGraphProgress, graphProgressTimer)
    } catch (e) {
      setGraph({ nodes: [], edges: [] })
      setGraphStatus('unavailable')
      finishProgress(setGraphProgress, graphProgressTimer)
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
    startEstimatedProgress(setAnalysisProgress, analysisProgressTimer)

    try {
      const data = await withTimeout('/analysis/generate', {
        method: 'POST',
        body: JSON.stringify({ case_ids: selected }),
      })

      setAnalysis(data.analysis || '')
      setContext(data.context || null)
      finishProgress(setAnalysisProgress, analysisProgressTimer)
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
          ? 'Analysis timed out after 5 minutes. Check NVIDIA_API_KEY and the backend server log.'
          : e.message
      )
    } finally {
      finishProgress(setAnalysisProgress, analysisProgressTimer)
      setGenerating(false)
    }
  }

  const openEntity = async (node) => {
    if (!node?.id) return
    setSelectedEntity({ node })
    setEntityLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('node_id', String(node.id))
      if (node.case_id) params.set('case_id', String(node.case_id))
      const details = await withTimeout('/graph/entity?' + params.toString())
      setSelectedEntity((prev) => ({ ...(prev || {}), details }))
    } catch (e) {
      setSelectedEntity((prev) => ({ ...(prev || {}), error: e.message }))
    } finally {
      setEntityLoading(false)
    }
  }

  const runGraphAnalysis = async (requestedCaseId = '') => {
    const caseId = requestedCaseId || graphAnalysisCaseId || selected[0] || ''
    if (!caseId) {
      setErr(t('err_select_case_graph_analysis'))
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
        ? 'Chat timed out after 5 minutes. Check NVIDIA_API_KEY, NVIDIA connectivity, and the backend log.'
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

  if (loading) return <Spinner label={t('loading_cases')} />

  return (
    <div className="page analysis-page">
      <div>
        <h2>{t('analysis_title')}</h2>
        <p className="muted">
          {t('analysis_subtitle')}
        </p>
      </div>

      {err && <ErrorBox message={err} />}

      {nvidiaReady && (
        <div className={nvidiaReady.configured ? 'info-box' : 'error-box'}>
          {nvidiaReady.configured
            ? t('nvidia_configured')
            : t('nvidia_missing')}
        </div>
      )}

      <Panel
        title={t('cases_for_analysis')}
        className="analysis-blue-panel"
        actions={
          <span className="muted small">
            {t('selected_count', { count: selected.length })}
          </span>
        }
      >
        {cases.length === 0 ? (
          <div className="empty muted">
            {t('no_authorized_cases')}
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
            {t('neo4j_sync_label')} <strong>{syncStatus.status}</strong>
            {syncStatus.synced_at ? ` · ${t('last_sync_label')} ${new Date(syncStatus.synced_at).toLocaleString()}` : ''}
            {syncStatus.error ? ` · ${syncStatus.error}` : ''}
            {syncStatus.status !== 'SYNCED' && (
              <button className="btn" type="button" onClick={resyncCase} style={{ marginLeft: 8 }}>
                {t('sync_case_to_neo4j')}
              </button>
            )}
          </div>
        )}

        <div className="analysis-actions">
          <div className="analysis-action-block">
            <button
              className="btn btn-primary analysis-generate-btn"
              disabled={
                !selected.length ||
                generating ||
                nvidiaReady?.configured === false
              }
              onClick={runAnalysis}
            >
              {generating ? t('btn_generating_analysis') : t('btn_generate_analysis')}
            </button>
          </div>

          <div className={'analysis-progress-slot' + (generating ? ' is-active' : '')}>
            {generating && <span className="analysis-progress-value">{analysisProgress}%</span>}
          </div>

          <div className="analysis-action-block">
            <button
              className="btn"
              disabled={!selected.length || graphStatus === 'generating'}
              onClick={generateGraph}
            >
              {graphStatus === 'generating' ? t('btn_generating_graph') : t('btn_generate_graph')}
            </button>
          </div>

          <div className={'analysis-progress-slot' + (graphStatus === 'generating' ? ' is-active' : '')}>
            {graphStatus === 'generating' && <span className="analysis-progress-value">{graphProgress}%</span>}
          </div>

          <div className="analysis-action-block analysis-graph-controls">
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
                    {t('graph_metrics_option', { caseId })}
                  </option>
                ))}
              </select>
            )}
            <button
              className="btn graph-analysis-btn"
              disabled={!selected.length || graphAnalysisLoading}
              onClick={() => runGraphAnalysis()}
            >
              {graphAnalysisLoading ? t('btn_running_graph_analysis') : t('btn_run_graph_analysis')}
            </button>
          </div>

          {selectedCases.length > 0 && (
            <span className="muted small analysis-current-selection">
              {t('analyzing_current_selection', { cases: selectedCases.map((c) => c.name).join(', ') })}
            </span>
          )}
        </div>
      </Panel>

      {context && (
        <div className="stat-grid">
          <StatCard label={t('stat_cases')} value={context.counts?.cases ?? 0} />
          <StatCard label={t('stat_people')} value={context.counts?.people ?? 0} />
          <StatCard label={t('stat_entities')} value={context.counts?.entities ?? 0} />
          <StatCard
            label={t('stat_relationships')}
            value={context.counts?.relationships ?? 0}
          />
          <StatCard label={t('stat_evidence')} value={context.counts?.evidence ?? 0} />
        </div>
      )}

      {graphAnalysis && (
        <Panel
          title={t('graph_analysis_panel_title')}
          actions={
            <span className="muted small">
              {t('graph_analysis_meta', {
                engine: graphAnalysis.engine || 'graph-engine',
                people: graphAnalysis.entity_count,
                links: graphAnalysis.edge_count ?? 0,
              })}
            </span>
          }
        >
          <div className="stat-grid">
            <StatCard
              label={t('stat_communities')}
              value={Object.keys(graphAnalysis.community_sizes || {}).length}
            />
            <StatCard
              label={t('stat_components')}
              value={new Set(
                (graphAnalysis.metrics?.connected_components || []).map((x) => x.componentId)
              ).size}
            />
            <StatCard
              label={t('stat_top_pagerank')}
              value={
                graphAnalysis.ranked_people?.[0]?.pagerank != null
                  ? graphAnalysis.ranked_people[0].pagerank.toFixed(4)
                  : '—'
              }
            />
            <StatCard
              label={t('stat_top_degree')}
              value={
                graphAnalysis.ranked_people?.[0]?.degree != null
                  ? graphAnalysis.ranked_people[0].degree.toFixed(2)
                  : '—'
              }
            />
          </div>

          <div className="info-box small">
            {t('graph_analysis_disclaimer', {
              engine: graphAnalysis.engine || 'local graph engine',
              mode: graphAnalysis.betweenness_mode || 'exact',
            })}
          </div>

          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('col_entity')}</th>
                  <th>{t('col_degree')}</th>
                  <th>{t('col_betweenness')}</th>
                  <th>{t('col_pagerank')}</th>
                  <th>{t('col_closeness')}</th>
                  <th>{t('col_community')}</th>
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
            <Panel title={t('panel_louvain')}>
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th>{t('col_entity')}</th><th>{t('col_community')}</th></tr></thead>
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

            <Panel title={t('panel_connected_components')}>
              <div className="table-scroll">
                <table className="table">
                  <thead><tr><th>{t('col_entity')}</th><th>{t('col_component')}</th></tr></thead>
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

          <Panel title={t('panel_similar_pairs')}>
            <div className="table-scroll">
              <table className="table">
                <thead><tr><th>{t('col_entity_a')}</th><th>{t('col_entity_b')}</th><th>{t('col_jaccard')}</th></tr></thead>
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

          <Panel title={t('panel_temporal_overview')}>
            <div className="stat-grid">
              <StatCard label={t('stat_events')} value={graphAnalysis.temporal?.event_count ?? 0} />
              <StatCard label={t('stat_timed_events')} value={graphAnalysis.temporal?.timed_event_count ?? 0} />
            </div>
          </Panel>
        </Panel>
      )}

      <div className="two-col analysis-workspace">
        <Panel title={t('suspicious_candidates_title')} className="analysis-blue-panel">
        {suspicious.length ? (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('col_person_a')}</th>
                  <th>{t('col_person_b')}</th>
                  <th>{t('col_score')}</th>
                  <th>{t('col_strength')}</th>
                  <th>{t('col_signals')}</th>
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
          <div className="empty muted">{t('no_candidates_ranked')}</div>
        )}
        <div className="info-box small">
          {t('candidates_disclaimer')}
        </div>
      </Panel>

        <Panel title={t('generated_case_analysis')} className="glass-panel analysis-summary-panel analysis-blue-panel">
          {analysis ? (
            <div className="analysis-summary-content">
              <MarkdownMessage text={analysis} />
            </div>
          ) : (
            <div className="empty muted">
              {t('prompt_select_cases_analyze')}
            </div>
          )}
        </Panel>

        <Panel title={t('investigation_assistant')} className="glass-panel chat-panel analysis-blue-panel">
          <div className="chat-shell">
            <div className="chat-messages">
              {messages.length === 0 && (
                <div className="empty muted">
                  {t('assistant_empty_prompt')}
                </div>
              )}

              {messages.map((m, i) => (
                <div
                  key={i}
                  className={'chat-message chat-' + m.role}
                >
                  <div className="chat-role">
                    {m.role === 'investigator'
                      ? t('role_investigator')
                      : t('role_nemotron')}
                  </div>
                  <div className="chat-content">{m.role === 'assistant' ? <MarkdownMessage text={m.content} /> : m.content}</div>
                  {m.role === 'assistant' && agentTools[i] && (
                    <div className="chat-tool-tag">{t('analysis_tool_tag', { tool: agentTools[i] })}</div>
                  )}
                </div>
              ))}

              {chatting && (
                <div className="chat-message chat-assistant chat-thinking">
                  <div className="chat-role">{t('role_nemotron')}</div>
                  <div className="chat-content muted">
                    <span className="thinking-dot"></span> {t('assistant_thinking')}
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
                  placeholder={t('chat_placeholder')}
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
                  title={t('chat_send_title')}
                  aria-label={t('chat_send')}
                >
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                  </svg>
                  <span>{t('chat_send')}</span>
                </button>
              </div>
            </form>
          </div>
        </Panel>
      </div>

      <Panel
        title={t('relevant_graph_title')}
        className="analysis-blue-panel"
        actions={
          graphStatus !== 'not_loaded' ? (
            <span className="muted small">
              {t('source_label', {
                source: graphStatus === 'neo4j' ? 'Neo4j' : graphStatus === 'sql-fallback' ? t('source_sql_fallback') : graphStatus,
              })}
            </span>
          ) : null
        }
      >
        {graph.nodes?.length ? (
          <NetworkGraph data={graph} onSelectNode={openEntity} />
        ) : (
          <div className="empty muted">
            {t('prompt_select_generate_graph')}
          </div>
        )}
      </Panel>

      {context?.relationships?.length > 0 && (
        <Panel title={t('top_evidence_relationships')}>
          <table className="table">
            <thead>
              <tr>
                <th>{t('col_person_a')}</th>
                <th>{t('col_person_b')}</th>
                <th>{t('col_strength')}</th>
                <th>{t('col_score')}</th>
                <th>{t('col_signals')}</th>
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

      {selectedEntity && (
        <div className="entity-modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedEntity(null) }}>
          <div className="entity-modal" role="dialog" aria-modal="true" aria-labelledby="entity-modal-title">
            <button className="entity-modal-close" type="button" onClick={() => setSelectedEntity(null)} aria-label="Close entity details">×</button>
            <div className="entity-modal-grid">
              <div>
                <div className="entity-modal-kicker">Entity details</div>
                <h3 id="entity-modal-title">{selectedEntity.details?.entity?.original_value || selectedEntity.node?.label || selectedEntity.node?.id}</h3>
                <div className="entity-detail-list">
                  <div><span>Type</span><strong>{selectedEntity.details?.entity?.entity_type || selectedEntity.node?.type || '—'}</strong></div>
                  <div><span>Normalized value</span><strong className="mono">{selectedEntity.details?.entity?.normalized_value || selectedEntity.node?.id || '—'}</strong></div>
                  <div><span>Confidence</span><strong>{selectedEntity.details?.entity?.confidence ?? '—'}</strong></div>
                  <div><span>Extraction method</span><strong>{selectedEntity.details?.entity?.extraction_method || '—'}</strong></div>
                  <div><span>Observed date</span><strong>{selectedEntity.details?.entity?.observed_date || '—'}</strong></div>
                  <div><span>Observed time</span><strong>{selectedEntity.details?.entity?.observed_time || '—'}</strong></div>
                </div>
              </div>
              <div className="entity-modal-source">
                <div className="entity-modal-kicker">Case & source</div>
                <div className="entity-source-card">
                  <div className="entity-source-label">Case</div>
                  <strong>{selectedEntity.details?.case?.name || selectedEntity.node?.case_id || 'Not available'}</strong>
                  <span className="muted small mono">{selectedEntity.details?.case?.id || selectedEntity.node?.case_id || ''}</span>
                </div>
                <div className="entity-source-card">
                  <div className="entity-source-label">Source file / report</div>
                  {selectedEntity.details?.document ? (
                    <>
                      <strong>{selectedEntity.details.document.filename || 'Unnamed document'}</strong>
                      <span className="muted small">{selectedEntity.details.document.file_type || 'Document'} · {selectedEntity.details.document.status || '—'}</span>
                      <span className="muted small mono">{selectedEntity.details.document.id || ''}</span>
                      {selectedEntity.details.document.created_at && <span className="muted small">Imported {new Date(selectedEntity.details.document.created_at).toLocaleString()}</span>}
                    </>
                  ) : <span className="muted">No source file is recorded for this entity.</span>}
                </div>
                {entityLoading && <div className="muted small">Loading full entity details…</div>}
                {selectedEntity.error && <div className="error-box small">{selectedEntity.error}</div>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
