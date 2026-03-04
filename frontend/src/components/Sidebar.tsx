import { type ReactNode } from 'react'
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
import EventRepeatIcon from '@mui/icons-material/EventRepeat'
import SettingsIcon from '@mui/icons-material/Settings'

const DRAWER_WIDTH = 240

interface NavItem {
  label: string
  path: string
  icon: ReactNode
  shortcut: number // Cmd+N
}

const NAV_SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: 'Collect',
    items: [
      { label: 'Inbox', path: '/', icon: <InboxIcon fontSize="small" />, shortcut: 1 },
      { label: 'Process', path: '/inbox/process', icon: <FilterListIcon fontSize="small" />, shortcut: 2 },
    ],
  },
  {
    heading: 'Lists',
    items: [
      { label: 'Next Actions', path: '/next-actions', icon: <PlaylistPlayIcon fontSize="small" />, shortcut: 3 },
      { label: 'Waiting For', path: '/waiting-for', icon: <HourglassEmptyIcon fontSize="small" />, shortcut: 4 },
      { label: 'Someday / Maybe', path: '/someday-maybe', icon: <LightbulbIcon fontSize="small" />, shortcut: 5 },
    ],
  },
  {
    heading: 'Reflect',
    items: [
      { label: 'Weekly Review', path: '/review', icon: <EventRepeatIcon fontSize="small" />, shortcut: 6 },
    ],
  },
  {
    heading: 'Organize',
    items: [
      { label: 'Projects', path: '/projects', icon: <FolderIcon fontSize="small" />, shortcut: 7 },
    ],
  },
]

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
      {NAV_SECTIONS.map((section, si) => (
        <Box key={section.heading}>
          {si > 0 && <Divider sx={{ my: 1 }} />}
          <Box sx={{ p: 2, pb: 1 }}>
            <Typography
              variant="overline"
              sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
            >
              {section.heading}
            </Typography>
          </Box>
          <List dense sx={{ px: 0 }}>
            {section.items.map((item) => (
              <ListItemButton
                key={item.path}
                selected={isSelected(item.path)}
                onClick={() => navigate(item.path)}
              >
                <ListItemIcon sx={{ minWidth: 36 }}>
                  {item.icon}
                </ListItemIcon>
                <ListItemText primary={item.label} />
                <Typography
                  variant="caption"
                  sx={{ color: 'text.disabled', fontSize: '0.7rem', fontFamily: 'monospace' }}
                >
                  {'\u2318'}{item.shortcut}
                </Typography>
              </ListItemButton>
            ))}
          </List>
        </Box>
      ))}

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
