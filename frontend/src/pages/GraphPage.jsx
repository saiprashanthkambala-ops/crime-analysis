import { useEffect, useState, lazy, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'
const NetworkGraph = lazy(() => import('../components/NetworkGraph'))
import { useI18n } from '../i18n'

const NODE_TYPES = ['person', 'phone', 'vehicle', 'account', 'location', 'case', 'event', 'evidence', 'document']

export default function GraphPage() {
  const { t } = useI18n()
  const [graph, setGraph] = useState(null)
  const [err, setErr] = useState('')
  const [selected, setSelected] = useState(null)
  const [active, setActive] = useState(() => new Set(NODE_TYPES))
  const navigate = useNavigate()

  useEffect(() => { api('/graph').then(setGraph).catch((e) => setErr(e.message)) }, [])

  const onSelectNode = (node) => {
    setSelected(node)
    if (node.type === 'person') navigate(`/persons/${node.id}`)
  }

  const toggle = (typeKey) => {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(typeKey)) next.delete(typeKey); else next.add(typeKey)
      return next
    })
  }

  if (err) return <ErrorBox message={err} />
  if (!graph) return <Spinner />

  const visibleNodes = (graph.nodes || []).filter((n) => active.has(n.data.type))
  const visibleIds = new Set(visibleNodes.map((n) => n.data.id))
  const visibleEdges = (graph.edges || []).filter(
    (e) => visibleIds.has(e.data.source) && visibleIds.has(e.data.target)
  )

  return (
    <div className="page app-section-page">
      <h2>{t('network_graph_title')}</h2>
      <p className="muted">{t('network_graph_subtitle')}</p>
      <div className="filter-row">
        {NODE_TYPES.map((typeKey) => (
          <label key={typeKey} className="toggle-chip">
            <input type="checkbox" checked={active.has(typeKey)} onChange={() => toggle(typeKey)} />
            {t('node_' + typeKey, null, typeKey)}
          </label>
        ))}
      </div>
      <Panel
        title={t('relationship_network_panel')}
        actions={<span className="muted small">{t('nodes_edges_count', { nodes: visibleNodes.length, edges: visibleEdges.length })}</span>}
      >
        <Suspense fallback={<Spinner />}>
          <NetworkGraph data={{ nodes: visibleNodes, edges: visibleEdges }} onSelectNode={onSelectNode} />
        </Suspense>
      </Panel>
    </div>
  )
}
