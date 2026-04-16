import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHotkeys } from 'react-hotkeys-hook'
import {
  Dialog,
  Box,
  TextField,
  List,
  ListItemButton,
  ListItemText,
  Typography,
  InputAdornment,
  Button,
  CircularProgress,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import FolderOpenIcon from '@mui/icons-material/FolderOpen'
import { api } from '../api'
import type { Project } from '../types'

export default function ProjectSwitcher() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  // null = not yet loaded (shows spinner), [] = loaded but empty
  const [projects, setProjects] = useState<Project[] | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Global Cmd+Shift+P / Ctrl+Shift+P shortcut
  useHotkeys(
    'meta+shift+p, ctrl+shift+p',
    (e) => {
      e.preventDefault()
      setOpen((prev) => !prev)
    },
    { enableOnFormTags: false },
  )

  // Fetch active projects when modal opens
  useEffect(() => {
    if (open && projects === null) {
      api.projects
        .list({ status: 'active' })
        .then((data) => setProjects(data))
        .catch(() => setProjects([]))
    }
  }, [open, projects])

  const handleClose = () => {
    setOpen(false)
    setSearch('')
    setProjects(null)
  }

  const filteredProjects = useMemo(() => {
    if (!projects) return []
    const sorted = [...projects].sort((a, b) => a.name.localeCompare(b.name))
    if (!search.trim()) return sorted
    const q = search.toLowerCase()
    return sorted.filter((p) => p.name.toLowerCase().includes(q))
  }, [projects, search])

  const handleSelect = (project: Project) => {
    navigate(`/projects/${project.id}`)
    handleClose()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      if (filteredProjects.length === 1) {
        handleSelect(filteredProjects[0])
      }
      // When multiple matches, Enter does nothing — must click or filter further
    }
    if (e.key === 'Escape') {
      handleClose()
    }
  }

  const singleMatch = filteredProjects.length === 1
  const loading = open && projects === null

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
      TransitionProps={{ onEntered: () => inputRef.current?.focus() }}
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
      <Box sx={{ p: 2 }} onKeyDown={handleKeyDown}>
        <TextField
          fullWidth
          autoFocus
          inputRef={inputRef}
          placeholder="Switch to project…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          variant="standard"
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                </InputAdornment>
              ),
              disableUnderline: true,
              sx: { fontSize: '1.1rem' },
            },
          }}
        />

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={24} />
          </Box>
        ) : filteredProjects.length === 0 ? (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ py: 3, textAlign: 'center' }}
          >
            {search.trim() ? `No projects match "${search}"` : 'No active projects'}
          </Typography>
        ) : (
          <List dense disablePadding sx={{ mt: 1, maxHeight: 320, overflowY: 'auto' }}>
            {filteredProjects.map((project) => (
              <ListItemButton
                key={project.id}
                onClick={() => handleSelect(project)}
                sx={{ borderRadius: 1 }}
              >
                <FolderOpenIcon sx={{ mr: 1.5, fontSize: 18, color: 'text.secondary' }} />
                <ListItemText
                  primary={project.name}
                  secondary={project.area || undefined}
                  primaryTypographyProps={{ noWrap: true }}
                  secondaryTypographyProps={{ noWrap: true }}
                />
              </ListItemButton>
            ))}
          </List>
        )}

        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            mt: 1.5,
          }}
        >
          <Typography variant="caption" color="text.secondary">
            {singleMatch
              ? 'Enter to switch'
              : filteredProjects.length > 1
                ? 'Filter further or click a project'
                : ''}
            &nbsp;·&nbsp;Esc to close
          </Typography>
          <Button
            size="small"
            variant="contained"
            disabled={!singleMatch}
            onClick={() => singleMatch && handleSelect(filteredProjects[0])}
          >
            Switch
          </Button>
        </Box>
      </Box>
    </Dialog>
  )
}
