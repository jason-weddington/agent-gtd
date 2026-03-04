import {
  Stepper,
  Step,
  StepButton,
  MobileStepper,
  LinearProgress,
  Box,
  useMediaQuery,
  useTheme,
} from '@mui/material'

const STEP_LABELS = [
  'Inbox',
  'Next Actions',
  'Waiting For',
  'Projects',
  'Someday',
  'Capture',
  'Summary',
]

interface ReviewStepperProps {
  activeStep: number
  onStepClick: (step: number) => void
}

export default function ReviewStepper({ activeStep, onStepClick }: ReviewStepperProps) {
  const theme = useTheme()
  const isNarrow = useMediaQuery(theme.breakpoints.down('md'))

  const progress = ((activeStep + 1) / STEP_LABELS.length) * 100

  if (isNarrow) {
    return (
      <Box sx={{ mb: 3 }}>
        <MobileStepper
          variant="dots"
          steps={STEP_LABELS.length}
          position="static"
          activeStep={activeStep}
          backButton={null}
          nextButton={null}
          sx={{ bgcolor: 'transparent', justifyContent: 'center' }}
        />
        <LinearProgress variant="determinate" value={progress} sx={{ mt: 1, borderRadius: 1, height: 4 }} />
      </Box>
    )
  }

  return (
    <Box sx={{ mb: 3 }}>
      <Stepper nonLinear activeStep={activeStep} alternativeLabel>
        {STEP_LABELS.map((label, index) => (
          <Step key={label} completed={index < activeStep}>
            <StepButton onClick={() => onStepClick(index)}>
              {label}
            </StepButton>
          </Step>
        ))}
      </Stepper>
      <LinearProgress variant="determinate" value={progress} sx={{ mt: 2, borderRadius: 1, height: 4 }} />
    </Box>
  )
}
