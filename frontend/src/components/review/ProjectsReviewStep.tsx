import { Typography, Box } from '@mui/material'
import FolderIcon from '@mui/icons-material/Folder'
import ProjectReviewCard from '../ProjectReviewCard'
import type { Item, Project } from '../../types'

interface ProjectsReviewStepProps {
  projects: Project[]
  projectItems: Record<string, Item[]>
  projectMap: Record<string, Project>
  onDone: (id: string) => void
  onDelete: (id: string) => void
  onUpdateStatus: (id: string, status: string) => void
}

export default function ProjectsReviewStep({
  projects,
  projectItems,
  projectMap,
  onDone,
  onDelete,
  onUpdateStatus,
}: ProjectsReviewStepProps) {
  return (
    <>
      <Typography variant="h6" gutterBottom>Review Projects</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Review each active project. Expand to see items and take action. Projects without a next action are flagged.
      </Typography>
      {projects.length === 0 ? (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <FolderIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No active projects
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Create a project to start organizing your work.
          </Typography>
        </Box>
      ) : (
        projects.map((project) => (
          <ProjectReviewCard
            key={project.id}
            project={project}
            items={projectItems[project.id] ?? []}
            projectMap={projectMap}
            onDone={onDone}
            onDelete={onDelete}
            onUpdateStatus={onUpdateStatus}
          />
        ))
      )}
    </>
  )
}
