import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'
import NetworkGraph from '../components/NetworkGraph'

export default function GraphPage() {
  const [graph, setGraph] = useState(null)
  const [err, setErr] = useState('')
  const [selected, setSelected] = useState(null)
  const navigate = useNavigate()

  useEffect(() => { api('/graph').then(setGraph).catch((e) => setErr(e.message)) }, [])

  const onSelectNode = (node) => {
    setSelected(node)
    if (node.type === 'person') navigate(`/persons/${node.id}`)
  }

  if (err) return <ErrorBox message={err} />
  if (!graph) return <Spinner />

  return (
    <div className="page">
      <h2>Network Graph</h2>
      <p className="muted">Interactive relationship network — a navigation layer, not an autonomous guilt engine.</p>
      <Panel
        title="Relationship Network"
        actions={<span className="muted small">{graph.nodes.length} nodes · {graph.edges.length} edges</span>}
      >
        <NetworkGraph data={graph} onSelectNode={onSelectNode} />
      </Panel>
    </div>
  )
}
