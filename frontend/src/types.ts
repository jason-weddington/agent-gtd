export interface UserResponse {
  id: string
  email: string
  createdAt: string
  isAdmin: boolean
}

export interface AdminUser {
  id: string
  email: string
  isAdmin: boolean
  createdAt: string
}

// --- Invites ---

export interface Invite {
  token: string
  issuedBy: string
  note: string
  createdAt: string
  usedAt: string | null
  usedBy: string | null
}

export interface CreatedInvite {
  token: string
  url: string
  note: string
  createdAt: string
}

export interface PasswordResetIssued {
  token: string
  url: string
  expiresAt: string
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
export type BuildEngine =
  | 'claude-code'
  | 'claude-code-ollama'
  | 'claude-code-glm'
  | 'claude-code-sonnet'
  | 'claude-code-haiku'
  | 'kiro'
export type RepoMode = 'monorepo' | 'workspace'

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
  /** Present for shared-with-me projects; absent for owned projects. */
  ownerEmail?: string
  /** True if the calling user owns this project. Undefined = treat as owner (solo context). */
  isOwner?: boolean
  /** Number of members (excluding owner). 0 or absent = unshared project. */
  memberCount?: number
  /** Per-project dispatch max turns override. Null = inherit from global setting. */
  dispatchMaxTurns?: number | null
  /** Per-project dispatch timeout override (minutes). Null = inherit from global setting. */
  dispatchTimeoutMinutes?: number | null
  /** Per-project plan-mode agent override. Null = inherit from global plan agent. */
  planDispatchAgent?: string | null
  /** Per-project build-mode agent override. Null = inherit from global build agent. */
  buildDispatchAgent?: string | null
  /** Quality-gate command for this project (shell string, runs from repo root; exit 0 = green). Null = not set. */
  gateCommand?: string | null
  /** Dispatch mode: 'monorepo' (single git_origin) or 'workspace' (multiple repos). Undefined = monorepo. */
  repoMode?: RepoMode
  /** Workspace repo URLs. Only used when repoMode === 'workspace'. */
  workspaceRepos?: string[]
  /** Number of open (non-done) items in this project. */
  totalItems: number
  /** Short preview of the project description (first line). Null when description is empty. */
  descriptionPreview: string | null
}

export interface MemberSummary {
  userId: string
  email: string
  addedAt: string
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
  lockedByRolloutId: string | null
  buildEngine: BuildEngine | null
  acceptanceCriteria: string[]
  filesToModify: Record<string, string>[]
  scopeOut: string[]
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
  itemId: string | null
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
  dispatchedByEmail?: string
  rolloutId: string | null
  dispatchHostUrl?: string
}

// --- Failure Feed ---

export interface FailedRun extends Run {
  itemTitle: string | null
  projectName: string
}

export interface StaleRun extends FailedRun {
  itemStatus: string
}

export interface RolloutFailureFeed {
  waveHalts: RolloutEvent[]
  failedRuns: FailedRun[]
}

// --- Wave Manager ---

export type RolloutStatus =
  | 'pending'
  | 'planning'
  | 'running'
  | 'halted'
  | 'failed'
  | 'completed'
  | 'cancelled'

export type RolloutItemStatus =
  | 'pending'
  | 'ready'
  | 'dispatched'
  | 'completed'
  | 'halted'
  | 'skipped'

export type RolloutEventActor = 'manager' | 'child-agent' | 'human'

export interface Rollout {
  id: string
  projectId: string
  leadUserId: string
  status: RolloutStatus
  haltReason: string | null
  startedAt: string | null
  endedAt: string | null
  createdAt: string
  updatedAt: string
  totalCount: number
  doneCount: number
  managerPhase: string | null
  managerCurrentItemId: string | null
  managerCurrentStep: string | null
  managerStateUpdatedAt: string | null
  managerCurrentItemTitle: string | null
}

export interface RolloutEvent {
  id: string
  rolloutId: string
  seq: number
  ts: string
  kind: string
  actor: RolloutEventActor
  decisionRule: string
  payload: Record<string, unknown>
}

export interface ActivityEvent {
  id: string
  rolloutId: string
  seq: number
  ts: string
  actor: string
  eventType: string
  itemId: string | null
  itemTitle: string | null
  runId: string | null
  decisionRule: string | null
  payload: Record<string, unknown>
}

export interface PlanRolloutResponse {
  rolloutId: string
  status: string
  itemCount: number
}

// --- Attachments ---

export interface AttachmentResponse {
  id: string
  itemId: string
  filename: string
  mimeType: string
  sizeBytes: number
  createdAt: string
}

// --- Dispatch Capabilities ---

export interface DispatchAgentInfo {
  name: string
  description: string
}

export interface DispatchCapabilities {
  engines: string[]
  versions: string[]
  agents: DispatchAgentInfo[]
  totalCapacity: number | null
}

export interface DispatchHost {
  id: string
  label: string
  url: string
  apiKeyPreview: string
  createdAt: string
}
