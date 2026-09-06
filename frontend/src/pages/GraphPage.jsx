import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'
import NetworkGraph from '../components/NetworkGraph'

const NODE_TYPES = ['person', 'phone', 'vehicle', 'account', 'location', 'case', 'event']

export default function GraphPage() {
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

  const toggle = (t) => {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t); else next.add(t)
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
    <div className="page">
      <h2>Network Graph</h2>
      <p className="muted">Interactive relationship network — a navigation layer, not an autonomous guilt engine.</p>
      <div className="filter-row">
        {NODE_TYPES.map((t) => (
          <label key={t} className="toggle-chip">
            <input type="checkbox" checked={active.has(t)} onChange={() => toggle(t)} />
            {t}
          </label>
        ))}
      </div>
      <Panel
        title="Relationship Network"
        actions={<span className="muted small">{visibleNodes.length} nodes · {visibleEdges.length} edges</span>}
      >
        <NetworkGraph data={{ nodes: visibleNodes, edges: visibleEdges }} onSelectNode={onSelectNode} />
      </Panel>
    </div>
  )
}
