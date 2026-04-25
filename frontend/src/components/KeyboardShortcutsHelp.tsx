import { useState } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { Dialog, Box, Typography } from '@mui/material'

interface ShortcutRow {
  keys: string
  description: string
}

const NAVIGATION_SHORTCUTS: ShortcutRow[] = [
  { keys: '\u2318\u21E71', description: 'Inbox' },
  { keys: '\u2318\u21E72', description: 'Process' },
  { keys: '\u2318\u21E73', description: 'Next Actions' },
  { keys: '\u2318\u21E74', description: 'Waiting For' },
  { keys: '\u2318\u21E75', description: 'Someday / Maybe' },
  { keys: '\u2318\u21E76', description: 'Weekly Review' },
  { keys: '\u2318\u21E77', description: 'Projects' },
]

const GLOBAL_SHORTCUTS: ShortcutRow[] = [
  { keys: '\u2318K', description: 'Quick capture' },
  { keys: '\u2318\u21E7P', description: 'Project switcher' },
  { keys: '?', description: 'Show keyboard shortcuts' },
]

const REMOTE_DISPATCH_SHORTCUTS: ShortcutRow[] = [
  { keys: 'D',       description: 'Dispatch — Build mode' },
  { keys: '\u21E7D', description: 'Dispatch — Plan mode'  },
]

interface ShortcutSectionProps {
  heading: string
  rows: ShortcutRow[]
  note?: string
}

function ShortcutSection({ heading, rows, note }: ShortcutSectionProps) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography
        variant="overline"
        sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
      >
        {heading}
      </Typography>
      <Box sx={{ mt: 0.5 }}>
        {rows.map((row) => (
          <Box
            key={row.keys}
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              py: 0.75,
            }}
          >
            <Typography variant="body2">{row.description}</Typography>
            <Typography
              variant="caption"
              sx={{ color: 'text.disabled', fontFamily: 'monospace', fontSize: '0.75rem' }}
            >
              {row.keys}
            </Typography>
          </Box>
        ))}
      </Box>
      {note && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ fontStyle: 'italic', display: 'block', mt: 0.5 }}
        >
          {note}
        </Typography>
      )}
    </Box>
  )
}

interface KeyboardShortcutsHelpProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

export default function KeyboardShortcutsHelp({ open: openProp, onOpenChange }: KeyboardShortcutsHelpProps = {}) {
  const [internalOpen, setInternalOpen] = useState(false)

  const open = openProp !== undefined ? openProp : internalOpen
  const setOpen = onOpenChange !== undefined
    ? onOpenChange
    : setInternalOpen

  useHotkeys(
    'shift+slash',
    (e) => {
      e.preventDefault()
      setOpen(!open)
    },
    { enableOnFormTags: false },
  )

  const handleClose = () => {
    setOpen(false)
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
      slotProps={{
        paper: {
          sx: {
            position: 'absolute',
            top: '10vh',
            m: 0,
            mx: 'auto',
            borderRadius: 2,
          },
        },
        backdrop: {
          sx: { backdropFilter: 'blur(4px)' },
        },
      }}
    >
      <Box sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
          Keyboard Shortcuts
        </Typography>

        <ShortcutSection heading="Navigation" rows={NAVIGATION_SHORTCUTS} />
        <ShortcutSection heading="Global" rows={GLOBAL_SHORTCUTS} />
        <ShortcutSection
          heading="Remote Dispatch"
          rows={REMOTE_DISPATCH_SHORTCUTS}
          note="Only available when a task is open in the right drawer for a project configured for remote dispatch."
        />

        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Esc to close
          </Typography>
        </Box>
      </Box>
    </Dialog>
  )
}
