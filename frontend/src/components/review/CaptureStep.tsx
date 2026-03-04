import { useState } from 'react'
import {
  Typography,
  TextField,
  Box,
  Chip,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import LightbulbIcon from '@mui/icons-material/Lightbulb'

interface CapturedItem {
  id: string
  title: string
}

interface CaptureStepProps {
  capturedItems: CapturedItem[]
  onCapture: (title: string) => Promise<void>
}

export default function CaptureStep({ capturedItems, onCapture }: CaptureStepProps) {
  const [text, setText] = useState('')
  const [capturing, setCapturing] = useState(false)

  const handleSubmit = async () => {
    const title = text.trim()
    if (!title) return
    setCapturing(true)
    try {
      await onCapture(title)
      setText('')
    } finally {
      setCapturing(false)
    }
  }

  return (
    <>
      <Typography variant="h6" gutterBottom>Capture Ideas</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Brainstorm new ideas, tasks, or anything on your mind. Items go to your inbox for later triage.
      </Typography>
      <TextField
        fullWidth
        placeholder="What's on your mind?"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
        disabled={capturing}
        size="small"
        sx={{ mb: 2 }}
        slotProps={{
          input: {
            endAdornment: capturing ? <CircularProgress size={20} /> : null,
          },
        }}
      />
      {capturedItems.length > 0 && (
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <Typography variant="subtitle2">Captured this session</Typography>
            <Chip label={capturedItems.length} size="small" variant="outlined" />
          </Box>
          <List dense>
            {capturedItems.map((item) => (
              <ListItem key={item.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, mb: 0.5 }}>
                <ListItemText primary={item.title} />
              </ListItem>
            ))}
          </List>
        </Box>
      )}
      {capturedItems.length === 0 && (
        <Box sx={{ textAlign: 'center', py: 3 }}>
          <LightbulbIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
          <Typography variant="body2" color="text.secondary">
            No items captured yet. Type above and press Enter.
          </Typography>
        </Box>
      )}
    </>
  )
}
