import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Cases from './pages/Cases'
import CaseDetail from './pages/CaseDetail'
import SearchPage from './pages/SearchPage'
import Profile from './pages/Profile'
import Relationships from './pages/Relationships'
import RelationshipDetail from './pages/RelationshipDetail'
import EvidencePage from './pages/EvidencePage'
import TimelinePage from './pages/TimelinePage'
import GraphPage from './pages/GraphPage'
import AdminPage from './pages/AdminPage'

function RequireAuth({ children }) {
  const { isAuthed } = useAuth()
  const location = useLocation()
  if (!isAuthed) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/cases" element={<Cases />} />
        <Route path="/cases/:caseId" element={<CaseDetail />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/persons/:personId" element={<Profile />} />
        <Route path="/relationships" element={<Relationships />} />
        <Route path="/relationships/:relId" element={<RelationshipDetail />} />
        <Route path="/evidence" element={<EvidencePage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
