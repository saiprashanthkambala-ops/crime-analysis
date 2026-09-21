import { createContext, useContext, useMemo, useState } from 'react'

const AnalysisRuntimeContext = createContext(null)

export function AnalysisRuntimeProvider({ children }) {
  // This provider intentionally lives above the route pages so analysis state
  // survives SPA navigation away from /analysis and back again.
  const [selected, setSelected] = useState([])
  const [analysis, setAnalysis] = useState('')
  const [context, setContext] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [syncStatus, setSyncStatus] = useState(null)
  const [graphStatus, setGraphStatus] = useState('not_loaded')
  const [graphAnalysis, setGraphAnalysis] = useState(null)
  const [graphAnalysisLoading, setGraphAnalysisLoading] = useState(false)
  const [graphAnalysisCaseId, setGraphAnalysisCaseId] = useState('')
  const [generating, setGenerating] = useState(false)
  const [messages, setMessages] = useState([])
  const [chatting, setChatting] = useState(false)
  const [agentTools, setAgentTools] = useState({})
  const [suspicious, setSuspicious] = useState([])
  const [analysisProgress, setAnalysisProgress] = useState(0)
  const [graphProgress, setGraphProgress] = useState(0)

  const value = useMemo(() => ({
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
  }), [
    selected, analysis, context, graph, syncStatus, graphStatus,
    graphAnalysis, graphAnalysisLoading, graphAnalysisCaseId, generating,
    messages, chatting, agentTools, suspicious, analysisProgress, graphProgress,
  ])

  return (
    <AnalysisRuntimeContext.Provider value={value}>
      {children}
    </AnalysisRuntimeContext.Provider>
  )
}

export function useAnalysisRuntime() {
  const value = useContext(AnalysisRuntimeContext)
  if (!value) {
    throw new Error('useAnalysisRuntime must be used inside AnalysisRuntimeProvider')
  }
  return value
}
