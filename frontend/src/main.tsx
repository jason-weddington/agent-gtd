import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource/roboto/300.css'
import '@fontsource/roboto/400.css'
import '@fontsource/roboto/500.css'
import '@fontsource/roboto/700.css'
import { ThemeProvider } from './contexts/ThemeContext'
import { AuthProvider } from './contexts/AuthContext'
import { EventStreamProvider } from './contexts/EventStreamContext'
import { QuickCaptureProvider } from './contexts/QuickCaptureContext'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <EventStreamProvider>
          <ThemeProvider>
            <QuickCaptureProvider>
              <App />
            </QuickCaptureProvider>
          </ThemeProvider>
        </EventStreamProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
