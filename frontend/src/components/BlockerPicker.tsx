import { useState, useCallback, useRef, useEffect } from 'react'
import Autocomplete from '@mui/material/Autocomplete'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import AddIcon from '@mui/icons-material/Add'
import CancelIcon from '@mui/icons-material/Cancel'
import { api, ApiError } from '../api'
import type { BlockerSummary, ItemStatus } from '../types'

const STATUS_COLORS: Record<ItemStatus, string> = {
  inbox: '#9e9e9e',
  new: '#9e9e9e',
  ready: '#2196f3',
  next_action: '#2196f3',
  waiting_for: '#9e9e9e',
  someday_maybe: '#9e9e9e',
  active: '#1976d2',
  review: '#ff9800',
  done: '#4caf50',
}

export interface BlockerPickerProps {
  itemId: string
  blockers: BlockerSummary[]
  onChange: (blockers: BlockerSummary[]) => void
  disabled?: boolean
}

export function BlockerPicker({ itemId, blockers, onChange, disabled }: BlockerPickerProps) {
  const [adding, setAdding] = useState(false)
  const [options, setOptions] = useState<BlockerSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const handleSearch = useCallback(
    (q: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (!q.trim()) {
        setOptions([])
        return
      }
      debounceRef.current = setTimeout(() => {
        void (async () => {
          setLoading(true)
          try {
            const results = await api.items.search(q)
            // Filter out already-attached blockers and the item itself
            setOptions(
              results.filter(
                (r) => r.id !== itemId && !blockers.some((b) => b.id === r.id),
              ),
            )
          } catch {
            setOptions([])
          } finally {
            setLoading(false)
          }
        })()
      }, 250)
    },
    [itemId, blockers],
  )

  const handleRemove = useCallback(
    async (blockerId: string) => {
      try {
        await api.items.blockers.remove(itemId, blockerId)
        onChange(blockers.filter((b) => b.id !== blockerId))
      } catch {
        // silently ignore remove errors — the blocker list will be stale
        // but the parent can refresh on next open
      }
    },
    [itemId, blockers, onChange],
  )

  const handleSelect = useCallback(
    async (value: BlockerSummary | null) => {
      if (!value) return
      setError(null)
      try {
        const added = await api.items.blockers.add(itemId, value.id)
        onChange([...blockers, added])
        setAdding(false)
        setInputValue('')
        setOptions([])
      } catch (err) {
        if (err instanceof ApiError && err.status === 400) {
          setError(err.detail)
        } else {
          setError('Failed to add blocker')
        }
      }
    },
    [itemId, blockers, onChange],
  )

  const blockerChipLabel = (b: BlockerSummary) => (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
      <Box
        sx={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          bgcolor: STATUS_COLORS[b.status] ?? '#9e9e9e',
          flexShrink: 0,
        }}
      />
      <Box
        component="span"
        title={`${b.id} | ${b.projectName ?? '—'} | ${b.title}`}
        sx={{
          maxWidth: 240,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          display: 'inline-block',
        }}
      >
        {b.id.slice(0, 8)} | {b.projectName ?? '—'} | {b.title}
      </Box>
    </Box>
  )

  return (
    <Box>
      {blockers.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
          {blockers.map((b) => (
            <Chip
              key={b.id}
              size="small"
              label={blockerChipLabel(b)}
              onDelete={disabled ? undefined : () => { void handleRemove(b.id) }}
              deleteIcon={<CancelIcon aria-label="Remove blocker" />}
              disabled={disabled}
            />
          ))}
        </Box>
      )}

      {adding ? (
        <Box>
          <Autocomplete<BlockerSummary>
            options={options}
            loading={loading}
            inputValue={inputValue}
            onInputChange={(_, val) => {
              setInputValue(val)
              handleSearch(val)
            }}
            onChange={(_, value) => { void handleSelect(value) }}
            getOptionLabel={(o) =>
              `${o.id.slice(0, 8)} | ${o.projectName ?? '—'} | ${o.title}`
            }
            isOptionEqualToValue={(o, v) => o.id === v.id}
            filterOptions={(x) => x}
            noOptionsText="No items found"
            renderInput={(params) => (
              <TextField
                {...params}
                label="Search items"
                size="small"
                autoFocus
                slotProps={{
                  input: {
                    ...params.InputProps,
                    endAdornment: (
                      <>
                        {loading && <CircularProgress size={16} color="inherit" />}
                        {params.InputProps.endAdornment}
                      </>
                    ),
                  },
                }}
              />
            )}
            renderOption={(props, option) => (
              <li {...props} key={option.id}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Box
                    component="span"
                    sx={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      bgcolor: STATUS_COLORS[option.status] ?? '#9e9e9e',
                      flexShrink: 0,
                      display: 'inline-block',
                    }}
                  />
                  <Box
                    component="span"
                    title={`${option.id} | ${option.projectName ?? '—'} | ${option.title}`}
                    sx={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {option.id.slice(0, 8)} | {option.projectName ?? '—'} | {option.title}
                  </Box>
                </Box>
              </li>
            )}
          />
          {error && (
            <Typography
              variant="caption"
              color="error"
              role="alert"
              sx={{ mt: 0.5, display: 'block' }}
            >
              {error}
            </Typography>
          )}
        </Box>
      ) : (
        <Button
          size="small"
          startIcon={<AddIcon />}
          onClick={() => {
            setAdding(true)
            setError(null)
          }}
          disabled={disabled}
        >
          Add blocker
        </Button>
      )}
    </Box>
  )
}
