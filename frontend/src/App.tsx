import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Inbox from './pages/Inbox'
import NextActions from './pages/NextActions'
import WaitingFor from './pages/WaitingFor'
import SomedayMaybe from './pages/SomedayMaybe'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import InboxProcessor from './pages/InboxProcessor'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Inbox />} />
        <Route path="/inbox/process" element={<InboxProcessor />} />
        <Route path="/next-actions" element={<NextActions />} />
        <Route path="/waiting-for" element={<WaitingFor />} />
        <Route path="/someday-maybe" element={<SomedayMaybe />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
