/**
 * RolloutStrip — compact 2-row strip summarising an active rollout.
 *
 * Pure presenter: receives rollout data and callbacks, does not fetch.
 * Rendered by RolloutBanner directly below the project header.
 *
 * Target layout:
 *   ⚙ Rollout 9c3d1abf · Phase: Merging · 2/5 items · 14m elapsed
 *      "Merging feat/efca5b81 → main"   [Halt] [Open details ▸]
 *
 * AC-4 through AC-14.
 */
import { useState } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material'
import SettingsIcon from '@mui/icons-material/Settings'
import { api, ApiError } from '../api'
import type { Rollout, RolloutStatus } from '../types'
import { formatElapsed } from '../utils'
import { getStatusColor, isStateStale } from './RolloutBanner'

// ---------------------------------------------------------------------------
// Internal colour helper (mirrors RolloutBanner's colorToSx, not re-exported)
// ---------------------------------------------------------------------------

type MuiColor = 'default' | 'info' | 'warning' | 'error' | 'success'

function colorToSx(color: MuiColor): Record<string, unknown> {
  const map: Record<MuiColor, string> = {
    default: 'action.hover',
    info: 'info.main',
    warning: 'warning.main',
    error: 'error.main',
    success: 'success.main',
  }
  return { bgcolor: map[color], color: color === 'default' ? 'text.primary' : 'common.white' }
}

// ---------------------------------------------------------------------------
// Statuses that show the Halt button (AC-10)
// ---------------------------------------------------------------------------

const HALTABLE_STATUSES: ReadonlySet<RolloutStatus> = new Set([
  'pending',
  'planning',
  'running',
])

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface RolloutStripProps {
  rollout: Rollout
  /** Called after a successful halt so the parent can re-fetch rollout state. */
  onHalt: () => void
  /** Called when the user clicks "Open details" — parent toggles details visibility. */
  onToggleDetails?: () => void
  /** Whether the details section is currently expanded (controls icon direction). */
  showDetails?: boolean
  /** Called when the user clicks the "Open details ▸" CTA — opens activity drawer and sets tab to 'rollout'. */
  onOpenActivityDrawer?: () => void
}

export default function RolloutStrip({
  rollout,
  onHalt,
  onOpenActivityDrawer,
}: RolloutStripProps) {
  // --- Halt confirmation dialog state (AC-11) ---
  const [haltOpen, setHaltOpen] = useState(false)
  const [haltReason, setHaltReason] = useState('')
  const [halting, setHalting] = useState(false)
  const [haltError, setHaltError] = useState<string | null>(null)

  const handleHaltConfirm = async () => {
    setHalting(true)
    setHaltError(null)
    try {
      await api.rollouts.halt(rollout.id, haltReason.trim())
      setHaltOpen(false)
      setHaltReason('')
      onHalt()
    } catch (err) {
      setHaltError(err instanceof ApiError ? err.detail : 'Failed to halt rollout')
    } finally {
      setHalting(false)
    }
  }

  const handleHaltClose = () => {
    if (halting) return
    setHaltOpen(false)
    setHaltReason('')
    setHaltError(null)
  }

  // --- Derived display values ---

  const statusColor = getStatusColor(rollout.status)

  // Row 1 tokens (AC-4)
  const shortId = rollout.id.slice(0, 8)
  const phaseToken = rollout.managerPhase
    ? `Phase: ${rollout.managerPhase}`
    : rollout.status
  const progressToken =
    rollout.totalCount > 0
      ? `${rollout.doneCount}/${rollout.totalCount} items`
      : null
  const elapsed = formatElapsed(rollout.startedAt)

  // Row 2 (AC-9, AC-10, AC-12)
  const hasStep = rollout.managerCurrentStep !== null
  const isHaltable = HALTABLE_STATUSES.has(rollout.status)
  const stale = isStateStale(rollout.managerStateUpdatedAt)

  return (
    <>
      <Box
        sx={{
          ...colorToSx(statusColor),
          borderRadius: 1,
          px: 1.5,
          py: 1,
          mb: 1,
        }}
      >
        {/* Row 1 — summary line (AC-4, AC-5, AC-6, AC-7, AC-8) */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
          <SettingsIcon sx={{ fontSize: 14 }} />
          <Typography variant="caption" sx={{ fontWeight: 600 }}>
            Rollout {shortId}
          </Typography>
          <Typography variant="caption" sx={{ mx: 0.25 }}>·</Typography>
          <Typography variant="caption">{phaseToken}</Typography>
          {progressToken !== null && (
            <>
              <Typography variant="caption" sx={{ mx: 0.25 }}>·</Typography>
              <Typography variant="caption">{progressToken}</Typography>
            </>
          )}
          <Typography variant="caption" sx={{ mx: 0.25 }}>·</Typography>
          <Typography variant="caption">{elapsed} elapsed</Typography>
        </Box>

        {/* Row 2 — current step + actions (AC-9, AC-10, AC-12) */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
          {hasStep ? (
            <Typography
              variant="caption"
              sx={{
                flex: 1,
                fontStyle: 'italic',
                color: stale ? 'text.disabled' : 'inherit',
                opacity: stale ? 0.8 : 1,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              &ldquo;{rollout.managerCurrentStep}&rdquo;
            </Typography>
          ) : (
            <Box sx={{ flex: 1 }} />
          )}

          {/* Halt button — only for haltable statuses (AC-10) */}
          {isHaltable && (
            <Button
              size="small"
              variant="outlined"
              color="inherit"
              sx={{
                minWidth: 0,
                py: 0,
                px: 1,
                fontSize: '0.7rem',
                lineHeight: 1.5,
                borderColor: 'currentColor',
              }}
              onClick={() => setHaltOpen(true)}
            >
              Halt
            </Button>
          )}

          {/* Open details CTA (AC-12, AC-13) */}
          {onOpenActivityDrawer && (
            <Button
              size="small"
              variant="text"
              color="inherit"
              sx={{ minWidth: 0, py: 0, px: 1, fontSize: '0.7rem', lineHeight: 1.5 }}
              onClick={onOpenActivityDrawer}
            >
              Open details ▸
            </Button>
          )}
        </Box>
      </Box>

      {/* Halt confirmation dialog (AC-11) */}
      <Dialog
        open={haltOpen}
        onClose={handleHaltClose}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Halt Rollout?</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            label="Reason (optional)"
            fullWidth
            value={haltReason}
            onChange={(e) => setHaltReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !halting) handleHaltConfirm()
            }}
            sx={{ mt: 1 }}
          />
          {haltError && (
            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 1 }}>
              {haltError}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleHaltClose} disabled={halting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={handleHaltConfirm}
            disabled={halting}
          >
            {halting ? <CircularProgress size={18} /> : 'Halt'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
