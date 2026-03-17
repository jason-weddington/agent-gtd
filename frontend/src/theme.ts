import { createTheme, type ThemeOptions } from '@mui/material/styles'

const shared: ThemeOptions = {
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
        },
      },
    },
    MuiPaper: {
      defaultProps: {
        elevation: 0,
      },
    },
  },
}

export const darkTheme = createTheme({
  ...shared,
  palette: {
    mode: 'dark',
    primary: {
      main: '#4a9eff',
      light: '#7db8ff',
      dark: '#0063dc',
    },
    secondary: {
      main: '#ff0084',
      light: '#ff4da6',
      dark: '#c4005f',
    },
    background: {
      default: '#1a1a1a',
      paper: '#242424',
    },
    text: {
      primary: '#e0e0e0',
      secondary: '#999999',
    },
    divider: 'rgba(255, 255, 255, 0.08)',
    action: {
      hover: 'rgba(255, 255, 255, 0.05)',
      selected: 'rgba(74, 158, 255, 0.12)',
    },
  },
  components: {
    ...shared.components,
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: '#141414',
          backgroundImage: 'none',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#1e1e1e',
          borderRight: '1px solid rgba(255, 255, 255, 0.06)',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          margin: '2px 8px',
          '&.Mui-selected': {
            backgroundColor: 'rgba(74, 158, 255, 0.12)',
            '&:hover': {
              backgroundColor: 'rgba(74, 158, 255, 0.18)',
            },
          },
        },
      },
    },
  },
})

export const lightTheme = createTheme({
  ...shared,
  palette: {
    mode: 'light',
    primary: {
      main: '#3d4f5f',
      light: '#637a8e',
      dark: '#2a3742',
    },
    secondary: {
      main: '#ff0084',
      light: '#ff4da6',
      dark: '#c4005f',
    },
    background: {
      default: '#f5f5f5',
      paper: '#ffffff',
    },
    text: {
      primary: '#1a1a1a',
      secondary: '#5f6368',
    },
    divider: 'rgba(0, 0, 0, 0.10)',
    action: {
      hover: 'rgba(0, 0, 0, 0.04)',
      selected: 'rgba(61, 79, 95, 0.10)',
    },
  },
  components: {
    ...shared.components,
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: '#ffffff',
          backgroundImage: 'none',
          borderBottom: '1px solid rgba(0, 0, 0, 0.10)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#fafafa',
          borderRight: '1px solid rgba(0, 0, 0, 0.08)',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          margin: '2px 8px',
          '&.Mui-selected': {
            backgroundColor: 'rgba(61, 79, 95, 0.10)',
            '&:hover': {
              backgroundColor: 'rgba(61, 79, 95, 0.16)',
            },
          },
        },
      },
    },
  },
})
