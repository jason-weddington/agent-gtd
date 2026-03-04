import { Box, Typography, Paper, Button } from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { useNavigate } from 'react-router-dom'

export interface ReviewStats {
  completed: number
  deleted: number
  triaged: number
  activated: number
  captured: number
}

interface SummaryStepProps {
  stats: ReviewStats
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, textAlign: 'center', flex: 1, minWidth: 100 }}>
      <Typography variant="h4" color="primary">{value}</Typography>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
    </Paper>
  )
}

export default function SummaryStep({ stats }: SummaryStepProps) {
  const navigate = useNavigate()

  return (
    <Box sx={{ textAlign: 'center' }}>
      <CheckCircleOutlineIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
      <Typography variant="h5" gutterBottom>
        Review Complete
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Here&apos;s what you accomplished during this review session.
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center', mb: 4 }}>
        <StatCard label="Completed" value={stats.completed} />
        <StatCard label="Deleted" value={stats.deleted} />
        <StatCard label="Triaged" value={stats.triaged} />
        <StatCard label="Activated" value={stats.activated} />
        <StatCard label="Captured" value={stats.captured} />
      </Box>
      <Button variant="contained" size="large" onClick={() => navigate('/')}>
        Back to Inbox
      </Button>
    </Box>
  )
}
