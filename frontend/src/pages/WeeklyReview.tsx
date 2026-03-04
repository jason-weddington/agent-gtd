import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  Alert,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import CheckIcon from '@mui/icons-material/Check'
import SnoozeIcon from '@mui/icons-material/Snooze'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import AssignmentIcon from '@mui/icons-material/Assignment'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import EventNoteIcon from '@mui/icons-material/EventNote'
import { api, ApiError } from '../api'
import type { Item, Project, ItemStatus } from '../types'
import { useEvents } from '../contexts/EventStreamContext'
import ReviewStepper from '../components/review/ReviewStepper'
import InboxReviewStep from '../components/review/InboxReviewStep'
import ItemReviewStep from '../components/review/ItemReviewStep'
import ProjectsReviewStep from '../components/review/ProjectsReviewStep'
import CaptureStep from '../components/review/CaptureStep'
import SummaryStep, { type ReviewStats } from '../components/review/SummaryStep'
import type { ReviewAction } from '../components/review/ReviewItemRow'

const TOTAL_STEPS = 7

export default function WeeklyReview() {
  const [activeStep, setActiveStep] = useState(0)

  // Data
  const [inboxItems, setInboxItems] = useState<Item[]>([])
  const [nextActionItems, setNextActionItems] = useState<Item[]>([])
  const [waitingForItems, setWaitingForItems] = useState<Item[]>([])
  const [somedayItems, setSomedayItems] = useState<Item[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [projectItems, setProjectItems] = useState<Record<string, Item[]>>({})
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Session tracking
  const [capturedItems, setCapturedItems] = useState<{ id: string; title: string }[]>([])
  const statsRef = useRef<ReviewStats>({
    completed: 0,
    deleted: 0,
    triaged: 0,
    activated: 0,
    captured: 0,
  })

  const { onEvent } = useEvents()
  const loadDataRef = useRef<() => Promise<void>>(undefined)

  const loadData = useCallback(async () => {
    try {
      const [inbox, nextActions, waitingFor, someday, activeProjects] = await Promise.all([
        api.items.inbox(),
        api.items.list({ status: 'next_action' }),
        api.items.list({ status: 'waiting_for' }),
        api.items.list({ status: 'someday_maybe' }),
        api.projects.list({ status: 'active' }),
      ])
      setInboxItems(inbox)
      setNextActionItems(nextActions)
      setWaitingForItems(waitingFor)
      setSomedayItems(someday)
      setProjects(activeProjects)

      const map: Record<string, Project> = {}
      for (const p of activeProjects) map[p.id] = p
      setProjectMap(map)

      const entries = await Promise.all(
        activeProjects.map(async (p) => [p.id, await api.projects.items(p.id)] as const),
      )
      setProjectItems(Object.fromEntries(entries))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load review data')
    } finally {
      setLoading(false)
    }
  }, [])

  loadDataRef.current = loadData

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const unsubs = [
      onEvent('item_created', () => { loadDataRef.current?.() }),
      onEvent('item_updated', () => { loadDataRef.current?.() }),
      onEvent('item_deleted', () => { loadDataRef.current?.() }),
      onEvent('project_updated', () => { loadDataRef.current?.() }),
    ]
    return () => { unsubs.forEach((u) => u()) }
  }, [onEvent])

  // --- Mutation handlers ---

  const handleDone = async (id: string) => {
    try {
      await api.items.update(id, { status: 'done' })
      statsRef.current.completed++
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to mark done')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.items.delete(id)
      statsRef.current.deleted++
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete')
    }
  }

  const handleUpdateStatus = async (id: string, status: string, extra?: Record<string, unknown>) => {
    try {
      await api.items.update(id, { status, ...extra })
      if (status === 'next_action') {
        statsRef.current.activated++
      } else {
        statsRef.current.triaged++
      }
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to update')
    }
  }

  const handleTriage = async (itemId: string, status: ItemStatus, projectId: string | null) => {
    try {
      const update: Record<string, unknown> = { status }
      if (projectId) update.projectId = projectId
      await api.items.update(itemId, update)
      statsRef.current.triaged++
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to triage')
    }
  }

  const handleCapture = async (title: string) => {
    try {
      const item = await api.items.capture(title)
      statsRef.current.captured++
      setCapturedItems((prev) => [...prev, { id: item.id, title: item.title }])
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to capture')
    }
  }

  // --- Navigation ---

  const handleNext = () => setActiveStep((s) => Math.min(s + 1, TOTAL_STEPS - 1))
  const handleBack = () => setActiveStep((s) => Math.max(s - 1, 0))

  // --- Render ---

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  const nextActionActions: ReviewAction[] = [
    { label: 'Done', icon: <CheckIcon fontSize="small" />, color: 'success', onClick: (item) => handleDone(item.id) },
    { label: 'Shelve', icon: <SnoozeIcon fontSize="small" />, onClick: (item) => handleUpdateStatus(item.id, 'someday_maybe') },
  ]

  const waitingForActions: ReviewAction[] = [
    { label: 'Done', icon: <CheckIcon fontSize="small" />, color: 'success', onClick: (item) => handleDone(item.id) },
    { label: 'Activate', icon: <PlayArrowIcon fontSize="small" />, onClick: (item) => handleUpdateStatus(item.id, 'next_action') },
  ]

  const somedayActions: ReviewAction[] = [
    { label: 'Activate', icon: <PlayArrowIcon fontSize="small" />, color: 'primary', onClick: (item) => handleUpdateStatus(item.id, 'next_action') },
    { label: 'Done', icon: <CheckIcon fontSize="small" />, color: 'success', onClick: (item) => handleDone(item.id) },
  ]

  const renderStep = () => {
    switch (activeStep) {
      case 0:
        return (
          <InboxReviewStep
            items={inboxItems}
            projectMap={projectMap}
            projects={projects}
            onDone={handleDone}
            onDelete={handleDelete}
            onTriage={handleTriage}
          />
        )
      case 1:
        return (
          <ItemReviewStep
            title="Next Actions"
            description="Review your next actions. Complete what's done, shelve what can wait."
            items={nextActionItems}
            projectMap={projectMap}
            actions={nextActionActions}
            onDelete={handleDelete}
            emptyIcon={<AssignmentIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />}
            emptyTitle="No next actions"
            emptyDescription="All caught up! Add next actions from your inbox or projects."
          />
        )
      case 2:
        return (
          <ItemReviewStep
            title="Waiting For"
            description="Check on items you're waiting for. Activate resolved ones, complete what's done."
            items={waitingForItems}
            projectMap={projectMap}
            actions={waitingForActions}
            onDelete={handleDelete}
            emptyIcon={<HourglassEmptyIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />}
            emptyTitle="Nothing waiting"
            emptyDescription="You're not waiting on anything right now."
          />
        )
      case 3:
        return (
          <ProjectsReviewStep
            projects={projects}
            projectItems={projectItems}
            projectMap={projectMap}
            onDone={handleDone}
            onDelete={handleDelete}
            onUpdateStatus={handleUpdateStatus}
          />
        )
      case 4:
        return (
          <ItemReviewStep
            title="Someday / Maybe"
            description="Review your someday list. Activate items you're ready to tackle."
            items={somedayItems}
            projectMap={projectMap}
            actions={somedayActions}
            onDelete={handleDelete}
            emptyIcon={<EventNoteIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />}
            emptyTitle="Someday list is empty"
            emptyDescription="Nothing parked for later."
          />
        )
      case 5:
        return (
          <CaptureStep
            capturedItems={capturedItems}
            onCapture={handleCapture}
          />
        )
      case 6:
        return <SummaryStep stats={statsRef.current} />
      default:
        return null
    }
  }

  return (
    <Box>
      <ReviewStepper activeStep={activeStep} onStepClick={setActiveStep} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Box sx={{ minHeight: 300 }}>
        {renderStep()}
      </Box>

      {/* Navigation buttons */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 3, pt: 2, borderTop: 1, borderColor: 'divider' }}>
        <Button
          onClick={handleBack}
          disabled={activeStep === 0}
          startIcon={<ArrowBackIcon />}
        >
          Back
        </Button>
        <Button
          variant="contained"
          onClick={handleNext}
          disabled={activeStep === TOTAL_STEPS - 1}
          endIcon={<ArrowForwardIcon />}
        >
          Next
        </Button>
      </Box>
    </Box>
  )
}
