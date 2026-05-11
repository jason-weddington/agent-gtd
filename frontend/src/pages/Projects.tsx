import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Typography,
  Button,
  Card,
  CardContent,
  CardActionArea,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress,
  Alert,
  InputAdornment,
  ToggleButtonGroup,
  ToggleButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Tooltip,
  FormControlLabel,
  Checkbox,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DoneIcon from '@mui/icons-material/Done'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import SearchIcon from '@mui/icons-material/Search'
import ViewModuleIcon from '@mui/icons-material/ViewModule'
import ViewListIcon from '@mui/icons-material/ViewList'
import PeopleIcon from '@mui/icons-material/People'
import PeopleOutlineIcon from '@mui/icons-material/PeopleOutline'
import { api, ApiError } from '../api'
import type { Project, ProjectStatus } from '../types'
import ProjectEditDialog from '../components/ProjectEditDialog'

const STATUS_COLORS: Record<ProjectStatus, 'success' | 'default' | 'warning' | 'error'> = {
  active: 'success',
  completed: 'default',
  on_hold: 'warning',
  cancelled: 'error',
}

const STATUS_LABELS: Record<ProjectStatus, string> = {
  active: 'Active',
  completed: 'Completed',
  on_hold: 'On Hold',
  cancelled: 'Cancelled',
}

type ViewMode = 'cards' | 'list'

const VIEW_MODE_KEY = 'agent_gtd-projects-view'
const SHOW_COMPLETED_KEY = 'agent_gtd-projects-show-completed'

export default function Projects() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>(
    () => (localStorage.getItem(VIEW_MODE_KEY) as ViewMode) || 'cards',
  )
  const [showCompletedProjects, setShowCompletedProjects] = useState<boolean>(
    () => localStorage.getItem(SHOW_COMPLETED_KEY) === 'true',
  )

  // Create/edit dialog
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Project | null>(null)

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadProjects = useCallback(async () => {
    try {
      const data = await api.projects.list()
      const sorted = [...data].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
      )
      setProjects(sorted)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to load projects')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  const ownedProjects = useMemo(
    () => projects.filter((p) => p.isOwner !== false),
    [projects],
  )
  const sharedProjects = useMemo(
    () => projects.filter((p) => p.isOwner === false),
    [projects],
  )

  const filteredOwned = useMemo(() => {
    const q = search.toLowerCase().trim()
    return ownedProjects.filter(
      (p) =>
        (showCompletedProjects || p.status !== 'completed') &&
        (!q ||
          p.name.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q) ||
          p.area.toLowerCase().includes(q)),
    )
  }, [ownedProjects, search, showCompletedProjects])

  const filteredShared = useMemo(() => {
    const q = search.toLowerCase().trim()
    return sharedProjects.filter(
      (p) =>
        (showCompletedProjects || p.status !== 'completed') &&
        (!q ||
          p.name.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q) ||
          p.area.toLowerCase().includes(q)),
    )
  }, [sharedProjects, search, showCompletedProjects])

  // Keep backward-compat for the "no projects" empty state
  const filteredProjects = useMemo(() => [...filteredOwned, ...filteredShared], [filteredOwned, filteredShared])

  const handleViewChange = (_: React.MouseEvent<HTMLElement>, newView: ViewMode | null) => {
    if (newView) {
      setViewMode(newView)
      localStorage.setItem(VIEW_MODE_KEY, newView)
    }
  }

  const handleShowCompletedChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked
    setShowCompletedProjects(checked)
    localStorage.setItem(SHOW_COMPLETED_KEY, String(checked))
  }

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (project: Project, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditing(project)
    setDialogOpen(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.projects.delete(deleteTarget.id)
      setDeleteTarget(null)
      await loadProjects()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to delete project')
    } finally {
      setDeleting(false)
    }
  }

  const handleComplete = async (project: Project, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.projects.update(project.id, { status: 'completed' })
      await loadProjects()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to complete project')
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}
      >
        <Typography variant="h5">Projects</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          New Project
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {projects.length === 0 ? (
        <Card sx={{ border: 1, borderColor: 'divider' }}>
          <CardContent sx={{ textAlign: 'center', py: 6 }}>
            <Typography variant="h6" color="text.secondary" gutterBottom>
              No projects yet
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Create your first project to organize your work.
            </Typography>
            <Button variant="outlined" startIcon={<AddIcon />} onClick={openCreate}>
              New Project
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center' }}>
            <TextField
              size="small"
              placeholder="Search projects…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              sx={{ flex: 1, maxWidth: 400 }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" color="action" />
                    </InputAdornment>
                  ),
                },
              }}
            />
            <FormControlLabel
              control={
                <Checkbox
                  size="small"
                  checked={showCompletedProjects}
                  onChange={handleShowCompletedChange}
                />
              }
              label={<Typography variant="body2">Show completed</Typography>}
            />
            <ToggleButtonGroup
              value={viewMode}
              exclusive
              onChange={handleViewChange}
              size="small"
            >
              <ToggleButton value="cards">
                <Tooltip title="Card view">
                  <ViewModuleIcon fontSize="small" />
                </Tooltip>
              </ToggleButton>
              <ToggleButton value="list">
                <Tooltip title="List view">
                  <ViewListIcon fontSize="small" />
                </Tooltip>
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>

          {filteredProjects.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
              {search.trim()
                ? `No projects match \u201c${search}\u201d`
                : 'All projects are completed. Enable \u201cShow completed\u201d to see them.'}
            </Typography>
          ) : (
            <>
              {/* ── Your projects ── */}
              {filteredOwned.length > 0 && viewMode === 'cards' && (
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                    gap: 2,
                    mb: filteredShared.length > 0 ? 3 : 0,
                  }}
                >
                  {filteredOwned.map((project) => (
                    <Card key={project.id} sx={{ border: 1, borderColor: 'divider' }}>
                      <CardActionArea onClick={() => navigate(`/projects/${project.id}`)}>
                        <CardContent>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1, alignItems: 'flex-start' }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: 1, minWidth: 0 }}>
                              <Typography variant="h6" noWrap sx={{ flex: 1 }}>
                                {project.name}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                                ({project.totalItems} items)
                              </Typography>
                              {(project.memberCount ?? 0) > 0 && (
                                <Tooltip title={`Shared with ${project.memberCount}`}>
                                  <IconButton
                                    size="small"
                                    onClick={(e) => { e.stopPropagation(); navigate(`/projects/${project.id}?tab=share`) }}
                                    sx={{ color: 'primary.main', p: 0.25 }}
                                  >
                                    <PeopleIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              )}
                            </Box>
                            <Chip
                              label={STATUS_LABELS[project.status]}
                              color={STATUS_COLORS[project.status]}
                              size="small"
                              sx={{ ml: 1, flexShrink: 0 }}
                            />
                          </Box>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                              minHeight: '2.4em',
                            }}
                          >
                            {project.description || 'No description'}
                          </Typography>
                          {project.area && (
                            <Chip
                              label={project.area}
                              size="small"
                              variant="outlined"
                              sx={{ mt: 1 }}
                            />
                          )}
                        </CardContent>
                      </CardActionArea>
                      <Box sx={{ display: 'flex', justifyContent: 'flex-end', px: 1, pb: 0.5 }}>
                        <IconButton size="small" onClick={(e) => openEdit(project, e)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                        {project.status !== 'completed' && (
                          <IconButton size="small" onClick={(e) => handleComplete(project, e)} title="Complete">
                            <DoneIcon fontSize="small" />
                          </IconButton>
                        )}
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation()
                            setDeleteTarget(project)
                          }}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    </Card>
                  ))}
                </Box>
              )}

              {filteredOwned.length > 0 && viewMode === 'list' && (
                <Card sx={{ border: 1, borderColor: 'divider', mb: filteredShared.length > 0 ? 3 : 0 }}>
                  <List disablePadding>
                    {filteredOwned.map((project, index) => (
                      <ListItem
                        key={project.id}
                        disablePadding
                        divider={index < filteredOwned.length - 1}
                      >
                        <ListItemButton
                          onClick={() => navigate(`/projects/${project.id}`)}
                          sx={{ flexGrow: 1, minWidth: 0, overflow: 'hidden' }}
                        >
                          <ListItemText
                            sx={{ overflow: 'hidden', minWidth: 0 }}
                            primary={
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Typography variant="body1" noWrap>
                                  {project.name}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                                  ({project.totalItems} items)
                                </Typography>
                                {(project.memberCount ?? 0) > 0 && (
                                  <Tooltip title={`Shared with ${project.memberCount}`}>
                                    <PeopleIcon
                                      fontSize="small"
                                      sx={{ color: 'primary.main', flexShrink: 0, cursor: 'pointer' }}
                                      onClick={(e) => { e.stopPropagation(); navigate(`/projects/${project.id}?tab=share`) }}
                                    />
                                  </Tooltip>
                                )}
                                <Chip
                                  label={STATUS_LABELS[project.status]}
                                  color={STATUS_COLORS[project.status]}
                                  size="small"
                                />
                                {project.area && (
                                  <Chip
                                    label={project.area}
                                    size="small"
                                    variant="outlined"
                                  />
                                )}
                              </Box>
                            }
                            secondary={project.description || undefined}
                            secondaryTypographyProps={{ sx: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                          />
                        </ListItemButton>
                        <Box sx={{ display: 'flex', gap: 0.5, flexShrink: 0, pr: 1 }}>
                          <IconButton size="small" onClick={(e) => openEdit(project, e)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                          {project.status !== 'completed' && (
                            <IconButton size="small" onClick={(e) => handleComplete(project, e)} title="Complete">
                              <DoneIcon fontSize="small" />
                            </IconButton>
                          )}
                          <IconButton
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteTarget(project)
                            }}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      </ListItem>
                    ))}
                  </List>
                </Card>
              )}

              {/* ── Shared with you ── */}
              {filteredShared.length > 0 && (
                <>
                  <Typography variant="h6" color="text.secondary" sx={{ mb: 1 }}>
                    Shared with you
                  </Typography>
                  {viewMode === 'cards' ? (
                    <Box
                      sx={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                        gap: 2,
                      }}
                    >
                      {filteredShared.map((project) => (
                        <Card key={project.id} sx={{ border: 1, borderColor: 'divider' }}>
                          <CardActionArea onClick={() => navigate(`/projects/${project.id}`)}>
                            <CardContent>
                              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1, alignItems: 'flex-start' }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: 1, minWidth: 0 }}>
                                  <Tooltip title={`Shared by ${project.ownerEmail ?? 'someone'}`}>
                                    <PeopleOutlineIcon fontSize="small" sx={{ color: 'text.secondary', flexShrink: 0 }} />
                                  </Tooltip>
                                  <Typography variant="h6" noWrap sx={{ flex: 1 }}>
                                    {project.name}
                                  </Typography>
                                  <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                                    ({project.totalItems} items)
                                  </Typography>
                                </Box>
                                <Chip
                                  label={STATUS_LABELS[project.status]}
                                  color={STATUS_COLORS[project.status]}
                                  size="small"
                                  sx={{ ml: 1, flexShrink: 0 }}
                                />
                              </Box>
                              <Typography
                                variant="body2"
                                color="text.secondary"
                                sx={{
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  overflow: 'hidden',
                                  minHeight: '2.4em',
                                }}
                              >
                                {project.description || 'No description'}
                              </Typography>
                              {project.ownerEmail && (
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                                  by {project.ownerEmail}
                                </Typography>
                              )}
                              {project.area && (
                                <Chip
                                  label={project.area}
                                  size="small"
                                  variant="outlined"
                                  sx={{ mt: 0.5 }}
                                />
                              )}
                            </CardContent>
                          </CardActionArea>
                        </Card>
                      ))}
                    </Box>
                  ) : (
                    <Card sx={{ border: 1, borderColor: 'divider' }}>
                      <List disablePadding>
                        {filteredShared.map((project, index) => (
                          <ListItem
                            key={project.id}
                            disablePadding
                            divider={index < filteredShared.length - 1}
                          >
                            <ListItemButton
                              onClick={() => navigate(`/projects/${project.id}`)}
                              sx={{ flexGrow: 1, minWidth: 0, overflow: 'hidden' }}
                            >
                              <ListItemText
                                sx={{ overflow: 'hidden', minWidth: 0 }}
                                primary={
                                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Tooltip title={`Shared by ${project.ownerEmail ?? 'someone'}`}>
                                      <PeopleOutlineIcon fontSize="small" sx={{ color: 'text.secondary', flexShrink: 0 }} />
                                    </Tooltip>
                                    <Typography variant="body1" noWrap>
                                      {project.name}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                                      ({project.totalItems} items)
                                    </Typography>
                                    <Chip
                                      label={STATUS_LABELS[project.status]}
                                      color={STATUS_COLORS[project.status]}
                                      size="small"
                                    />
                                    {project.area && (
                                      <Chip
                                        label={project.area}
                                        size="small"
                                        variant="outlined"
                                      />
                                    )}
                                  </Box>
                                }
                                secondary={project.ownerEmail ? `Shared by ${project.ownerEmail}` : project.description || undefined}
                                secondaryTypographyProps={{ sx: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                              />
                            </ListItemButton>
                          </ListItem>
                        ))}
                      </List>
                    </Card>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      {/* Create/Edit Dialog */}
      <ProjectEditDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        editing={editing}
        onSaved={() => { loadProjects() }}
      />

      {/* Delete Confirmation */}
      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} fullWidth maxWidth="xs">
        <DialogTitle>Delete Project</DialogTitle>
        <DialogContent>
          <Typography>
            Delete &ldquo;{deleteTarget?.name}&rdquo;? All items and notes in this
            project will also be deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? <CircularProgress size={20} /> : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
