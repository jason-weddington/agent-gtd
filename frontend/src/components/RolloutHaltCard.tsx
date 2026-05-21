/**
 * RolloutHaltCard — shown when wave_run.status === 'halted'.
 *
 * AC-12 through AC-18.
 */
import { useState, useEffect } from 'react'
import {
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material'
import { api, ApiError } from '../api'
import type { Comment, RolloutEvent, Rollout } from '../types'
import MarkdownContent from './MarkdownContent'

interface RolloutHaltCardProps {
  waveRun: Rollout
  /** The most recent wave_halted event (for comment_id and item_id). */
  latestHaltEvent: RolloutEvent | null
  onResume: () => void
  onSkip: () => void
  onAbort: () => void
}

export default function RolloutHaltCard({
  waveRun,
  latestHaltEvent,
  onResume,
  onSkip,
  onAbort,
}: RolloutHaltCardProps) {
  // --- Comment fetching (AC-14) ---
  const commentId =
    latestHaltEvent
      ? (latestHaltEvent.payload.comment_id as string | undefined) ?? null
      : null
  const [comment, setComment] = useState<Comment | null>(null)
  const [commentLoading, setCommentLoading] = useState(false)

  useEffect(() => {
    if (!commentId) {
      setComment(null)
      return
    }
    setCommentLoading(true)
    api.comments
      .get(commentId)
      .then((c) => setComment(c))
      .catch(() => setComment(null))
      .finally(() => setCommentLoading(false))
  }, [commentId])

  // --- Resume dialog (AC-16) ---
  const [resumeOpen, setResumeOpen] = useState(false)
  const [answerText, setAnswerText] = useState('')
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)

  const handleResume = async () => {
    if (!answerText.trim()) return
    setResuming(true)
    setResumeError(null)
    try {
      await api.rollouts.resume(waveRun.id, answerText.trim())
      setResumeOpen(false)
      setAnswerText('')
      onResume()
    } catch (err) {
      setResumeError(err instanceof ApiError ? err.detail : 'Failed to resume rollout')
    } finally {
      setResuming(false)
    }
  }

  // --- Skip dialog (AC-17) ---
  const [skipping, setSkipping] = useState(false)
  const [skipError, setSkipError] = useState<string | null>(null)

  const offendingItemId =
    latestHaltEvent
      ? (latestHaltEvent.payload.item_id as string | undefined) ?? null
      : null

  const handleSkip = async () => {
    if (!offendingItemId) return
    setSkipping(true)
    setSkipError(null)
    try {
      await api.rollouts.completeItem(waveRun.id, offendingItemId, 'skipped')
      onSkip()
    } catch (err) {
      setSkipError(err instanceof ApiError ? err.detail : 'Failed to skip item')
    } finally {
      setSkipping(false)
    }
  }

  // --- Dismiss (AC-4) ---
  const [dismissing, setDismissing] = useState(false)
  const [dismissError, setDismissError] = useState<string | null>(null)

  const handleDismiss = async () => {
    setDismissing(true)
    setDismissError(null)
    try {
      await api.rollouts.dismiss(waveRun.id)
      onAbort()
    } catch (err) {
      setDismissError(err instanceof ApiError ? err.detail : 'Failed to dismiss rollout')
    } finally {
      setDismissing(false)
    }
  }

  // --- Abort dialog (AC-18) ---
  const [abortOpen, setAbortOpen] = useState(false)
  const [aborting, setAborting] = useState(false)
  const [abortError, setAbortError] = useState<string | null>(null)

  const handleAbort = async () => {
    setAborting(true)
    setAbortError(null)
    try {
      await api.rollouts.cancel(waveRun.id, 'Manually aborted by user')
      setAbortOpen(false)
      onAbort()
    } catch (err) {
      setAbortError(err instanceof ApiError ? err.detail : 'Failed to abort rollout')
    } finally {
      setAborting(false)
    }
  }

  return (
    <>
      {/* Halt card with warning-coloured left border (AC-12) */}
      <Card
        sx={{
          borderLeft: 4,
          borderColor: 'warning.main',
          mb: 2,
        }}
      >
        <CardContent>
          {/* Halt reason (AC-13) */}
          <Typography variant="subtitle2" fontWeight={600} gutterBottom>
            {waveRun.haltReason ?? 'Wave halted'}
          </Typography>

          {/* Manager comment (AC-14) */}
          {commentId && (
            <Box sx={{ mt: 1 }}>
              {commentLoading ? (
                <CircularProgress size={16} />
              ) : comment ? (
                <MarkdownContent>{comment.contentMarkdown}</MarkdownContent>
              ) : null}
            </Box>
          )}

          {skipError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {skipError}
            </Typography>
          )}
          {dismissError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {dismissError}
            </Typography>
          )}
          {abortError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {abortError}
            </Typography>
          )}
        </CardContent>

        {/* Action buttons (AC-15) */}
        <CardActions sx={{ px: 2, pb: 2, gap: 1 }}>
          <Button
            variant="contained"
            color="primary"
            size="small"
            onClick={() => setResumeOpen(true)}
          >
            Resume with answer
          </Button>
          <Button
            variant="outlined"
            size="small"
            onClick={handleSkip}
            disabled={!offendingItemId || skipping}
          >
            {skipping ? <CircularProgress size={14} /> : 'Skip this item'}
          </Button>
          <Button
            variant="outlined"
            size="small"
            onClick={handleDismiss}
            disabled={dismissing}
          >
            {dismissing ? <CircularProgress size={14} /> : 'Dismiss Wave'}
          </Button>
          <Button
            variant="outlined"
            color="error"
            size="small"
            onClick={() => setAbortOpen(true)}
          >
            Abort rollout
          </Button>
        </CardActions>
      </Card>

      {/* Resume dialog (AC-16) */}
      <Dialog
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Resume Wave</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            label="Your answer or instruction"
            multiline
            minRows={3}
            fullWidth
            value={answerText}
            onChange={(e) => setAnswerText(e.target.value)}
            sx={{ mt: 1 }}
          />
          {resumeError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {resumeError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResumeOpen(false)} disabled={resuming}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleResume}
            disabled={resuming || !answerText.trim()}
          >
            {resuming ? <CircularProgress size={18} /> : 'Submit'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Abort confirmation dialog (AC-18) */}
      <Dialog
        open={abortOpen}
        onClose={() => setAbortOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Abort Wave?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Are you sure you want to abort this rollout? All remaining items will
            be marked skipped.
          </Typography>
          {abortError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {abortError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAbortOpen(false)} disabled={aborting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleAbort}
            disabled={aborting}
          >
            {aborting ? <CircularProgress size={18} /> : 'Abort'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
