import { useState } from 'react'
import { useInertGuard } from '../hooks/useInertGuard'
import { Outlet, useNavigate } from 'react-router-dom'
import { useHotkeys } from 'react-hotkeys-hook'
import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Tooltip,
  Avatar,
  Menu,
  MenuItem,
  ListItemIcon,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import MenuIcon from '@mui/icons-material/Menu'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import SettingsIcon from '@mui/icons-material/Settings'
import LogoutIcon from '@mui/icons-material/Logout'
import AppsIcon from '@mui/icons-material/Apps'
import BoltIcon from '@mui/icons-material/Bolt'
import { useThemeMode } from '../contexts/ThemeContext'
import { useAuth } from '../contexts/AuthContext'
import { useQuickCapture } from '../contexts/QuickCaptureContext'
import Sidebar from './Sidebar'
import ProjectSwitcher from './ProjectSwitcher'
import KeyboardShortcutsHelp from './KeyboardShortcutsHelp'
import ActiveRunsIndicator from './ActiveRunsIndicator'

export default function Layout() {
  const { mode, toggleTheme } = useThemeMode()
  const { user, logout, localMode } = useAuth()
  const { openCapture } = useQuickCapture()
  const navigate = useNavigate()
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [sidebarOpen, setSidebarOpen] = useState(!isMobile)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  // Guaranteed-recovery guard: removes stranded MUI inert/aria-hidden that can
  // be left on the app-root element when a modal unmounts without cleanup,
  // silently killing Sidebar nav until the user reloads.  See useInertGuard.ts.
  useInertGuard()

  useHotkeys('escape', () => {
    // Don't navigate if a dialog is open
    if (document.querySelector('[role="dialog"]')) return
    navigate('/')
  }, { enableOnFormTags: false, enableOnContentEditable: false })

  const displayName = user?.email ?? ''

  const handleLogout = () => {
    setAnchorEl(null)
    logout()
    navigate('/login')
  }

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            sx={{ mr: 1 }}
          >
            <MenuIcon />
          </IconButton>

          <Box sx={{ display: 'flex', alignItems: 'center', flexGrow: 1 }}>
            <Box
              onClick={() => navigate('/')}
              sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
            >
              <AppsIcon sx={{ mr: 1, color: 'primary.light' }} />
              <Typography
                variant="h6"
                component="div"
                sx={{ fontWeight: 700, letterSpacing: -0.5 }}
              >
                Agent GTD
              </Typography>
            </Box>
          </Box>

          <Typography
            variant="caption"
            onClick={() => setShortcutsOpen(true)}
            sx={{
              color: 'rgba(255,255,255,0.5)',
              mr: 1.5,
              display: { xs: 'none', md: 'block' },
              userSelect: 'none',
              cursor: 'pointer',
              '&:hover': { color: 'rgba(255,255,255,0.8)' },
            }}
          >
            shift+?
          </Typography>

          <Tooltip title="Quick capture (Cmd+K)">
            <IconButton color="inherit" onClick={openCapture} sx={{ mr: 1 }}>
              <BoltIcon />
            </IconButton>
          </Tooltip>

          <ActiveRunsIndicator />

          <Tooltip title={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            <IconButton color="inherit" onClick={toggleTheme} sx={{ mr: 1 }}>
              {mode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>

          <Tooltip title={displayName}>
            <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} sx={{ p: 0 }}>
              <Avatar
                sx={{
                  width: 32,
                  height: 32,
                  bgcolor: 'primary.main',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
              >
                {displayName.charAt(0).toUpperCase()}
              </Avatar>
            </IconButton>
          </Tooltip>

          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={() => setAnchorEl(null)}
            transformOrigin={{ horizontal: 'right', vertical: 'top' }}
            anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
            slotProps={{
              paper: {
                sx: { mt: 1, minWidth: 180 },
              },
            }}
          >
            <MenuItem
              onClick={() => {
                setAnchorEl(null)
                navigate('/settings')
              }}
            >
              <ListItemIcon>
                <SettingsIcon fontSize="small" />
              </ListItemIcon>
              Settings
            </MenuItem>
            {!localMode && (
              <MenuItem onClick={handleLogout}>
                <ListItemIcon>
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                Sign Out
              </MenuItem>
            )}
          </Menu>
        </Toolbar>
      </AppBar>

      <Sidebar open={sidebarOpen} isMobile={isMobile} onClose={() => setSidebarOpen(false)} />

      <ProjectSwitcher />
      <KeyboardShortcutsHelp open={shortcutsOpen} onOpenChange={setShortcutsOpen} />

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          mt: '64px',
          p: 3,
          minHeight: 'calc(100vh - 64px)',
          transition: 'margin-left 225ms cubic-bezier(0, 0, 0.2, 1)',
          overflowX: 'hidden',
        }}
      >
        <Outlet />
      </Box>
    </Box>
  )
}
