import { createContext, useContext, useState, useCallback } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import QuickCapture from '../components/QuickCapture'

export interface ActiveProject {
  id: string
  name: string
}

interface QuickCaptureContextType {
  openCapture: () => void
  setActiveProject: (project: ActiveProject | null) => void
}

const QuickCaptureContext = createContext<QuickCaptureContextType>({
  openCapture: () => {},
  setActiveProject: () => {},
})

export function QuickCaptureProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [activeProject, setActiveProject] = useState<ActiveProject | null>(null)

  const openCapture = useCallback(() => setOpen(true), [])
  const closeCapture = useCallback(() => setOpen(false), [])

  // Global Cmd+K / Ctrl+K shortcut
  useHotkeys('meta+k, ctrl+k', (e) => {
    e.preventDefault()
    setOpen((prev) => !prev)
  }, {
    enableOnFormTags: false,
  })

  return (
    <QuickCaptureContext.Provider value={{ openCapture, setActiveProject }}>
      {children}
      <QuickCapture open={open} onClose={closeCapture} activeProject={activeProject} />
    </QuickCaptureContext.Provider>
  )
}

export function useQuickCapture() {
  return useContext(QuickCaptureContext)
}
