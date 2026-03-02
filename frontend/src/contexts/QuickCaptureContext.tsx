import { createContext, useContext, useState, useCallback } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import QuickCapture from '../components/QuickCapture'

interface QuickCaptureContextType {
  openCapture: () => void
}

const QuickCaptureContext = createContext<QuickCaptureContextType>({
  openCapture: () => {},
})

export function QuickCaptureProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)

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
    <QuickCaptureContext.Provider value={{ openCapture }}>
      {children}
      <QuickCapture open={open} onClose={closeCapture} />
    </QuickCaptureContext.Provider>
  )
}

export function useQuickCapture() {
  return useContext(QuickCaptureContext)
}
