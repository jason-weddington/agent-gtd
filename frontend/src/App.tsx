import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import AdminRoute from './components/AdminRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import Inbox from './pages/Inbox'
import NextActions from './pages/NextActions'
import WaitingFor from './pages/WaitingFor'
import SomedayMaybe from './pages/SomedayMaybe'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import InboxProcessor from './pages/InboxProcessor'
import Settings from './pages/Settings'
import WeeklyReview from './pages/WeeklyReview'
import AdminInvites from './pages/AdminInvites'
import AdminUsers from './pages/AdminUsers'
import ResetPassword from './pages/ResetPassword'
import Runs from './pages/Runs'
import RolloutDetail from './pages/RolloutDetail'

export default function App() {
  // Prevent Escape from exiting browser fullscreen (Safari).
  // Always intercept Escape at the capture phase so the browser never sees it.
  // MUI dialogs, react-hotkeys-hook, and our own handlers still fire normally
  // since they listen on the React/DOM event, not the default browser action.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
      }
    }
    document.addEventListener('keydown', handler, true)
    return () => document.removeEventListener('keydown', handler, true)
  }, [])

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/reset-password" element={<ResetPassword />} />
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
        <Route path="/review" element={<WeeklyReview />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/rollouts/:rolloutId" element={<RolloutDetail />} />
      </Route>
      <Route
        element={
          <AdminRoute>
            <Layout />
          </AdminRoute>
        }
      >
        <Route path="/admin/invites" element={<AdminInvites />} />
        <Route path="/admin/users" element={<AdminUsers />} />
      </Route>
    </Routes>
  )
}
