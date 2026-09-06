import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'

const NODE_STYLE = {
  person: { color: '#22d3ee', shape: 'ellipse' },
  phone: { color: '#a78bfa', shape: 'round-rectangle' },
  vehicle: { color: '#fbbf24', shape: 'round-rectangle' },
  account: { color: '#34d399', shape: 'diamond' },
  location: { color: '#fb7185', shape: 'hexagon' },
  case: { color: '#f472b6', shape: 'round-rectangle' },
  event: { color: '#94a3b8', shape: 'triangle' },
}

export default function NetworkGraph({ data, onSelectNode }) {
  const ref = useRef(null)
  const cyRef = useRef(null)

  useEffect(() => {
    if (!ref.current || !data) return
    if (cyRef.current) cyRef.current.destroy()

    const cy = cytoscape({
      container: ref.current,
      elements: [
        ...(data.nodes || []).map((n) => ({
          data: { ...n.data, label: n.data.label || n.data.id },
        })),
        ...(data.edges || []).map((e) => ({ data: e.data })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#334155',
            'border-color': '#475569',
            'border-width': 1,
            label: 'data(label)',
            'font-size': 10,
            color: '#cbd5e1',
            'text-valign': 'bottom',
            'text-margin-y': 4,
            width: 26,
            height: 26,
          },
        },
        {
          selector: 'node[type="person"]',
          style: { 'background-color': '#22d3ee', width: 32, height: 32 },
        },
        {
          selector: 'node[type="phone"]',
          style: { 'background-color': '#a78bfa', shape: 'round-rectangle' },
        },
        {
          selector: 'node[type="vehicle"]',
          style: { 'background-color': '#fbbf24', shape: 'round-rectangle' },
        },
        {
          selector: 'node[type="account"]',
          style: { 'background-color': '#34d399', shape: 'diamond' },
        },
        {
          selector: 'node[type="location"]',
          style: { 'background-color': '#fb7185', shape: 'hexagon' },
        },
        {
          selector: 'node[type="case"]',
          style: { 'background-color': '#f472b6', shape: 'round-rectangle' },
        },
        {
          selector: 'node[type="event"]',
          style: { 'background-color': '#94a3b8', shape: 'triangle' },
        },
        {
          selector: 'edge',
          style: {
            width: 1.2,
            'line-color': '#475569',
            'target-arrow-color': '#475569',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': 7,
            color: '#64748b',
            'text-rotation': 'autorotate',
          },
        },
        {
          selector: 'edge[type="CONNECTED_TO"]',
          style: { 'line-color': '#38bdf8', 'target-arrow-color': '#38bdf8', width: 1.6 },
        },
        {
          selector: 'edge[type="CALLED"], edge[type="TRANSFERRED_TO"]',
          style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b' },
        },
      ],
      layout: { name: 'cose', animate: false, padding: 30, nodeRepulsion: 6000 },
    })

    cy.on('tap', 'node', (evt) => {
      const node = evt.target.data()
      if (onSelectNode) onSelectNode(node)
    })

    cyRef.current = cy
    return () => { if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null } }
  }, [data])

  return (
    <div className="graph-container">
      <div ref={ref} className="graph-canvas" />
      <div className="graph-legend">
        {Object.entries(NODE_STYLE).map(([k, v]) => (
          <span key={k} className="legend-item">
            <span className="legend-dot" style={{ background: v.color }} /> {k}
          </span>
        ))}
      </div>
    </div>
  )
}
