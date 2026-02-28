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
import NotesIcon from '@mui/icons-material/StickyNote2'
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
      <Box sx={{ p: 2, pb: 1 }}>
        <Typography
          variant="overline"
          sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}
        >
          Menu
        </Typography>
      </Box>

      <List dense sx={{ px: 0 }}>
        <ListItemButton selected={isSelected('/')} onClick={() => navigate('/')}>
          <ListItemIcon sx={{ minWidth: 36 }}>
            <NotesIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Notes" />
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
