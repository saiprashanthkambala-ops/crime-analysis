import { createContext, useContext, useMemo, useState } from 'react'

const AnalysisRuntimeContext = createContext(null)
const STORAGE_KEY = 'crime_analysis_runtime_v1'

function readInitialState() {
  return {
    selected: [],
    analysis: '',
    context: null,
    graph: { nodes: [], edges: [] },
    syncStatus: null,
    graphStatus: 'not_loaded',
    graphAnalysis: null,
    graphAnalysisLoading: false,
    graphAnalysisCaseId: '',
    generating: false,
    messages: [],
    chatting: false,
    agentTools: {},
    suspicious: [],
    analysisProgress: 0,
    graphProgress: 0,
  }
}

function loadPersistedState() {
  // sessionStorage intentionally lasts across SPA navigation but is cleared
  // by a full browser/tab reload/close, matching the requested lifecycle.
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return readInitialState()
    const parsed = JSON.parse(raw)
    return { ...readInitialState(), ...parsed }
  } catch {
    return readInitialState()
  }
}

export function AnalysisRuntimeProvider({ children }) {
  const [state, setState] = useState(loadPersistedState)

  const update = (key) => (value) => {
    setState((prev) => ({
      ...prev,
      [key]: typeof value === 'function' ? value(prev[key]) : value,
    }))
  }

  const clearRuntime = () => setState(readInitialState())

  useMemo(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      // Ignore storage quota/private-mode failures; in-memory navigation state still works.
    }
    return null
  }, [state])

  const value = useMemo(() => ({
    ...state,
    setSelected: update('selected'),
    setAnalysis: update('analysis'),
    setContext: update('context'),
    setGraph: update('graph'),
    setSyncStatus: update('syncStatus'),
    setGraphStatus: update('graphStatus'),
    setGraphAnalysis: update('graphAnalysis'),
    setGraphAnalysisLoading: update('graphAnalysisLoading'),
    setGraphAnalysisCaseId: update('graphAnalysisCaseId'),
    setGenerating: update('generating'),
    setMessages: update('messages'),
    setChatting: update('chatting'),
    setAgentTools: update('agentTools'),
    setSuspicious: update('suspicious'),
    setAnalysisProgress: update('analysisProgress'),
    setGraphProgress: update('graphProgress'),
    clearRuntime,
  }), [state])

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
