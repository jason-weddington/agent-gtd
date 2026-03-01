export interface UserResponse {
  id: string
  email: string
  createdAt: string
}

export interface AuthResponse {
  token: string
  user: UserResponse
}

// --- GTD Enums ---

export type ProjectStatus = 'active' | 'completed' | 'on_hold' | 'cancelled'
export type ItemStatus =
  | 'inbox'
  | 'next_action'
  | 'waiting_for'
  | 'scheduled'
  | 'someday_maybe'
  | 'active'
  | 'done'
  | 'cancelled'
export type Priority = 'low' | 'normal' | 'high' | 'urgent'

// --- Domain Types ---

export interface Project {
  id: string
  name: string
  description: string
  status: ProjectStatus
  area: string
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
