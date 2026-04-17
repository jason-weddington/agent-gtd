export interface UserResponse {
  id: string
  email: string
  createdAt: string
}

export interface AuthResponse {
  token: string
  user: UserResponse
}

// --- API Keys ---

export interface ApiKeyInfo {
  id: string
  name: string
  hashPrefix: string
  createdAt: string
}

// --- GTD Enums ---

export type ProjectStatus = 'active' | 'completed' | 'on_hold' | 'cancelled'
export type ItemStatus =
  | 'inbox'
  | 'new'
  | 'ready'
  | 'next_action'
  | 'waiting_for'
  | 'someday_maybe'
  | 'active'
  | 'review'
  | 'done'
export type Priority = 'low' | 'normal' | 'high' | 'urgent'

// --- Domain Types ---

export interface Project {
  id: string
  name: string
  description: string
  status: ProjectStatus
  area: string
  gitOrigin: string
  kbProjectRef: string
  createdAt: string
  updatedAt: string
}

export interface Item {
  id: string
  projectId: string | null
  title: string
  description: string
  status: ItemStatus
  priority: Priority
  dueDate: string | null
  completedAt: string | null
  createdBy: string
  assignedTo: string
  waitingOn: string
  sortOrder: number
  labels: string[]
  blockers?: BlockerSummary[]
  version: number
  createdAt: string
  updatedAt: string
}

export interface Note {
  id: string
  projectId: string
  title: string
  contentMarkdown: string
  labels: string[]
  createdAt: string
  updatedAt: string
}

export interface Comment {
  id: string
  projectId: string | null
  itemId: string | null
  contentMarkdown: string
  createdBy: string
  createdAt: string
  updatedAt: string
}

export interface BlockerSummary {
  id: string
  title: string
  status: ItemStatus
  projectId: string | null
  projectName: string | null
}

export type RunStatus = 'pending' | 'cloning' | 'running' | 'success' | 'failed' | 'timeout' | 'cancelled'

export interface Run {
  id: string
  itemId: string
  projectId: string
  status: RunStatus
  featureBranch: string
  workspaceDir: string
  maxTurns: number
  mode: string
  startedAt: string | null
  finishedAt: string | null
  errorMsg: string
  createdAt: string
  updatedAt: string
}
