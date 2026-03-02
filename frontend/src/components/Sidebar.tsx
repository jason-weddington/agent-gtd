import { useLocation, useNavigate } from 'react-router-dom'
import {
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Divider,
  Typography,
  Box,
} from '@mui/material'
import InboxIcon from '@mui/icons-material/Inbox'
import FilterListIcon from '@mui/icons-material/FilterList'
import PlaylistPlayIcon from '@mui/icons-material/PlaylistPlay'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import LightbulbIcon from '@mui/icons-material/Lightbulb'
import FolderIcon from '@mui/icons-material/Folder'
import SettingsIcon from '@mui/icons-material/Settings'

const DRAWER_WIDTH = 240

interface SidebarProps {
  open: boolean
}

export default function Sidebar({ open }: SidebarProps) {
  const location = useLocation()
  const navigate = useNavigate()

  const isSelected = (path: string) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname.startsWith(path)
  }

  return (
    <Drawer
      variant="persistent"
      anchor="left"
      open={open}
      sx={{
        width: open ? DRAWER_WIDTH : 0,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
          top: '64px',
          height: 'calc(100% - 64px)',
        },
      }}
    >
      {/* Collect */}
      <Box sx={{ p: 2, pb: 1 }}>
        <Typography
          variant="overline"
          sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
        >
          Collect
        </Typography>
      </Box>
      <List dense sx={{ px: 0 }}>
        <ListItemButton selected={isSelected('/')} onClick={() => navigate('/')}>
          <ListItemIcon sx={{ minWidth: 36 }}>
            <InboxIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Inbox" />
        </ListItemButton>
        <ListItemButton
          selected={isSelected('/inbox/process')}
          onClick={() => navigate('/inbox/process')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <FilterListIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Process" />
        </ListItemButton>
      </List>

      <Divider sx={{ my: 1 }} />

      {/* Lists */}
      <Box sx={{ px: 2, pb: 1 }}>
        <Typography
          variant="overline"
          sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
        >
          Lists
        </Typography>
      </Box>
      <List dense sx={{ px: 0 }}>
        <ListItemButton
          selected={isSelected('/next-actions')}
          onClick={() => navigate('/next-actions')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <PlaylistPlayIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Next Actions" />
        </ListItemButton>
        <ListItemButton
          selected={isSelected('/waiting-for')}
          onClick={() => navigate('/waiting-for')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <HourglassEmptyIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Waiting For" />
        </ListItemButton>
        <ListItemButton
          selected={isSelected('/someday-maybe')}
          onClick={() => navigate('/someday-maybe')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <LightbulbIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Someday / Maybe" />
        </ListItemButton>
      </List>

      <Divider sx={{ my: 1 }} />

      {/* Organize */}
      <Box sx={{ px: 2, pb: 1 }}>
        <Typography
          variant="overline"
          sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
        >
          Organize
        </Typography>
      </Box>
      <List dense sx={{ px: 0 }}>
        <ListItemButton
          selected={isSelected('/projects')}
          onClick={() => navigate('/projects')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <FolderIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Projects" />
        </ListItemButton>
      </List>

      <Divider sx={{ my: 1 }} />

      <List dense sx={{ px: 0 }}>
        <ListItemButton
          selected={isSelected('/settings')}
          onClick={() => navigate('/settings')}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>
            <SettingsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Settings" />
        </ListItemButton>
      </List>
    </Drawer>
  )
}
