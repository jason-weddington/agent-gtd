/**
 * RolloutEventFeed — apt-style structured event table for a rollout run.
 *
 * Pure presentational component. Parent owns data fetching.
 * AC-6, AC-7, AC-8, AC-9.
 */
import {
  Box,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import CodeIcon from '@mui/icons-material/Code'
import PersonIcon from '@mui/icons-material/Person'
import type { ActivityEvent } from '../types'

interface RolloutEventFeedProps {
  events: ActivityEvent[]
  loading: boolean
  onItemClick?: (itemId: string) => void
  /** Optional: project-relative short IDs for linking. Not used for routing — just display. */
  projectId?: string
}

// --- Actor icon + label mapping (AC-8) ---

function ActorCell({ actor }: { actor: string }) {
  const config: Partial<Record<string, { icon: React.ReactNode; label: string }>> = {
    manager: { icon: <SmartToyIcon fontSize="small" />, label: 'Manager' },
    'child-agent': { icon: <CodeIcon fontSize="small" />, label: 'Agent' },
    human: { icon: <PersonIcon fontSize="small" />, label: 'Human' },
  }
  const { icon, label } = config[actor] ?? { icon: null, label: actor }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
      {icon}
      <Typography variant="caption">{label}</Typography>
    </Box>
  )
}

// --- Timestamp formatter (local HH:MM:SS) ---

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return ts
  }
}

// --- Message summariser ---

function formatMessage(event: ActivityEvent): string {
  const { eventType, payload } = event
  switch (eventType) {
    case 'wave_halted':
      return `Halted: ${String(payload.reason ?? '')}`
    case 'wave_resumed':
      return 'Wave resumed by human'
    case 'wave_started':
      return 'Wave started'
    case 'wave_completed':
      return 'Wave completed'
    case 'wave_replanned':
      return 'Wave replanned'
    case 'item_dispatched':
      return `Dispatched item ${String(payload.itemId ?? '').slice(0, 8)}`
    case 'item_outcome': {
      const outcome = String(payload.outcome ?? '')
      const itemId = String(payload.itemId ?? '').slice(0, 8)
      return `Item ${itemId}: ${outcome}`
    }
    default:
      return eventType
  }
}

// --- Short item ID helper ---

export function shortId(id: unknown): string {
  if (typeof id !== 'string' || !id) return '—'
  return id.slice(0, 8)
}

export default function RolloutEventFeed({ events, loading, onItemClick }: RolloutEventFeedProps) {
  // AC-6: filter out manager_state_update events — state ≠ activity log.
  const displayEvents = events.filter((e) => e.eventType !== 'manager_state_update')

  if (loading) {
    return (
      <Box sx={{ mt: 1 }}>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} variant="rectangular" height={32} sx={{ mb: 0.5 }} />
        ))}
      </Box>
    )
  }

  if (displayEvents.length === 0) {
    // AC-9: empty state
    return (
      <Box sx={{ py: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No events yet
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer>
      <Table size="small" sx={{ tableLayout: 'fixed' }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: 80 }}>
              <Typography variant="caption" fontWeight={600}>
                Time
              </Typography>
            </TableCell>
            <TableCell sx={{ width: 100 }}>
              <Typography variant="caption" fontWeight={600}>
                Actor
              </Typography>
            </TableCell>
            <TableCell sx={{ width: 80 }}>
              <Typography variant="caption" fontWeight={600}>
                Item
              </Typography>
            </TableCell>
            <TableCell>
              <Typography variant="caption" fontWeight={600}>
                Message
              </Typography>
            </TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {displayEvents.map((event) => {
            const itemId = event.itemId
            const itemTitle = event.itemTitle
            const tooltipTitle = itemId
              ? `${itemTitle ?? itemId} • ${itemId}`
              : ''
            return (
              <TableRow key={event.id} hover>
                <TableCell>
                  <Typography variant="caption" fontFamily="monospace">
                    {formatTimestamp(event.ts)}
                  </Typography>
                </TableCell>
                <TableCell>
                  <ActorCell actor={event.actor} />
                </TableCell>
                <TableCell
                  onClick={() => itemId && onItemClick?.(itemId)}
                  sx={{ cursor: itemId ? 'pointer' : 'default' }}
                >
                  <Tooltip title={tooltipTitle} placement="top">
                    <Typography
                      variant="caption"
                      fontFamily="monospace"
                      sx={
                        itemId
                          ? { '&:hover': { textDecoration: 'underline', color: 'primary.main' } }
                          : undefined
                      }
                    >
                      {itemTitle ?? shortId(itemId)}
                    </Typography>
                  </Tooltip>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {formatMessage(event)}
                  </Typography>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
