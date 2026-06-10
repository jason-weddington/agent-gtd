/**
 * Tests for ProjectEditDialog: [Monorepo | Workspace] toggle + repo list editor.
 *
 * AC-3, AC-4, AC-5, AC-6, AC-7, AC-13 (owner gating).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import ProjectEditDialog from '../ProjectEditDialog'
import type { Project } from '../../types'

// ---------------------------------------------------------------------------
// Mock the api module (KanbanBoard.test.tsx pattern)
// ---------------------------------------------------------------------------
vi.mock('../../api', () => ({
  api: {
    dispatch: {
      capabilities: vi.fn(),
    },
    settings: {
      getDispatch: vi.fn(),
    },
    projects: {
      create: vi.fn(),
      update: vi.fn(),
    },
  },
  ApiError: class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.name = 'ApiError'
      this.status = status
      this.detail = detail
    }
  },
}))

import { api } from '../../api'

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeMockProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'proj-123',
    name: 'Test Project',
    description: '',
    status: 'active',
    area: '',
    gitOrigin: 'git@github.com:org/repo.git',
    kbProjectRef: '',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    totalItems: 0,
    descriptionPreview: null,
    isOwner: true,
    ...overrides,
  }
}

const noop = () => {}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.dispatch.capabilities).mockResolvedValue({ engines: [], versions: [], agents: [], totalCapacity: null })
  vi.mocked(api.settings.getDispatch).mockResolvedValue({
    engine: 'claude-code',
    planAgentName: '',
    buildAgentName: '',
    defaultMaxTurns: 100,
    defaultTimeoutMinutes: 90,
    managerDefaultTimeoutMinutes: 240,
    serviceUrl: '',
    serviceApiKeyPreview: '',
  })
  vi.mocked(api.projects.create).mockResolvedValue(makeMockProject())
  vi.mocked(api.projects.update).mockResolvedValue(makeMockProject())
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProjectEditDialog', () => {
  describe('(a) create mode: toggle defaults to Monorepo', () => {
    it('renders the Monorepo toggle as selected by default', async () => {
      render(
        <ProjectEditDialog open={true} onClose={noop} editing={null} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Monorepo' })).toBeInTheDocument()
      })
      // Monorepo button should be selected (aria-pressed=true for ToggleButton)
      expect(screen.getByRole('button', { name: 'Monorepo' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute('aria-pressed', 'false')
      // Git Origin field is visible
      expect(screen.getByLabelText(/Git Origin/i)).toBeInTheDocument()
    })
  })

  describe('(b) switching to Workspace mode', () => {
    it('removes the Git Origin field and renders exactly one empty Repo URL row', async () => {
      render(
        <ProjectEditDialog open={true} onClose={noop} editing={null} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })
      // Exactly one Repo URL row
      const repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields).toHaveLength(1)
      expect(repoFields[0]).toHaveValue('')
    })
  })

  describe('(c) parity rule: Save enabled with non-empty name and zero non-empty repos in workspace mode', () => {
    it('Save is enabled when workspace mode has an empty repo list', async () => {
      render(
        <ProjectEditDialog open={true} onClose={noop} editing={null} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      // Enter project name so !name.trim() is false
      fireEvent.change(screen.getByLabelText(/Name/i), { target: { value: 'My Workspace Project' } })
      // Switch to workspace mode (one empty repo row by default)
      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      // Save/Create button should be enabled (empty workspace is valid)
      const saveBtn = screen.getByRole('button', { name: /create/i })
      expect(saveBtn).not.toBeDisabled()
    })
  })

  describe('(d) edit mode: update payload includes repoMode, trimmed workspaceRepos, and preserved gitOrigin', () => {
    it('calls api.projects.update with correct workspace payload', async () => {
      const editing = makeMockProject({
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'workspace',
        workspaceRepos: ['git@github.com:org/a.git', 'git@github.com:org/b.git'],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => {
        expect(vi.mocked(api.projects.update)).toHaveBeenCalledOnce()
      })

      const [, payload] = vi.mocked(api.projects.update).mock.calls[0]
      expect(payload).toMatchObject({
        repoMode: 'workspace',
        workspaceRepos: ['git@github.com:org/a.git', 'git@github.com:org/b.git'],
        gitOrigin: 'git@github.com:org/repo.git',
      })
    })

    it('drops empty rows from workspaceRepos on save', async () => {
      const editing = makeMockProject({
        repoMode: 'workspace',
        workspaceRepos: ['git@github.com:org/a.git'],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Add repo' })).toBeInTheDocument()
      })

      // Add an empty row
      fireEvent.click(screen.getByRole('button', { name: 'Add repo' }))

      await waitFor(() => {
        expect(screen.getAllByLabelText(/Repo URL/i)).toHaveLength(2)
      })

      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => {
        expect(vi.mocked(api.projects.update)).toHaveBeenCalledOnce()
      })

      const [, payload] = vi.mocked(api.projects.update).mock.calls[0]
      // Empty row should be dropped
      expect((payload as Record<string, unknown>).workspaceRepos).toEqual(['git@github.com:org/a.git'])
    })
  })

  describe('(e) owner gating: non-owner save omits all owner-only fields', () => {
    it('calls api.projects.update WITHOUT owner fields when isOwner=false', async () => {
      const editing = makeMockProject({
        isOwner: false,
        gitOrigin: 'git@github.com:org/repo.git',
        planDispatchAgent: 'some-agent',
        buildDispatchAgent: 'some-agent',
        repoMode: 'monorepo',
        workspaceRepos: [],
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => {
        expect(vi.mocked(api.projects.update)).toHaveBeenCalledOnce()
      })

      const [, payload] = vi.mocked(api.projects.update).mock.calls[0]
      expect(payload).not.toHaveProperty('gitOrigin')
      expect(payload).not.toHaveProperty('repoMode')
      expect(payload).not.toHaveProperty('workspaceRepos')
      expect(payload).not.toHaveProperty('planDispatchAgent')
      expect(payload).not.toHaveProperty('buildDispatchAgent')
      // Non-owner fields are still present
      expect(payload).toHaveProperty('name')
      expect(payload).toHaveProperty('description')
    })
  })

  describe('(f) owner gating: owner save includes repoMode, gitOrigin, workspaceRepos', () => {
    it('calls api.projects.update WITH owner fields when isOwner is not false', async () => {
      const editing = makeMockProject({
        isOwner: true,
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'monorepo',
        workspaceRepos: [],
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => {
        expect(vi.mocked(api.projects.update)).toHaveBeenCalledOnce()
      })

      const [, payload] = vi.mocked(api.projects.update).mock.calls[0]
      expect(payload).toHaveProperty('repoMode', 'monorepo')
      expect(payload).toHaveProperty('gitOrigin', 'git@github.com:org/repo.git')
      expect(payload).toHaveProperty('workspaceRepos')
    })
  })

  describe('(g) owner gating: toggle and repo-list controls are disabled for non-owners', () => {
    it('renders toggle and repo controls disabled when isOwner=false', async () => {
      const editing = makeMockProject({
        isOwner: false,
        repoMode: 'workspace',
        workspaceRepos: ['git@github.com:org/a.git'],
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Monorepo' })).toBeInTheDocument()
      })

      // Toggle buttons should be disabled
      expect(screen.getByRole('button', { name: 'Monorepo' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Workspace' })).toBeDisabled()

      // Repo URL inputs and Add repo button should be disabled
      const repoInput = screen.getByLabelText(/Repo URL/i)
      expect(repoInput).toBeDisabled()

      expect(screen.getByRole('button', { name: 'Add repo' })).toBeDisabled()
    })
  })
  describe('(h) pre-seed workspace repo list from existing gitOrigin on monorepo→workspace toggle', () => {
    it('(1) edit mode, monorepo with non-empty gitOrigin → click Workspace → one Repo URL row equal to gitOrigin', async () => {
      const editing = makeMockProject({
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'monorepo',
        workspaceRepos: [],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      const repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields).toHaveLength(1)
      expect(repoFields[0]).toHaveValue('git@github.com:org/repo.git')
    })

    it('(2) edit mode, monorepo with non-empty gitOrigin → click Workspace → Save → correct payload', async () => {
      const editing = makeMockProject({
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'monorepo',
        workspaceRepos: [],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Save' }))

      await waitFor(() => {
        expect(vi.mocked(api.projects.update)).toHaveBeenCalledOnce()
      })

      const [, payload] = vi.mocked(api.projects.update).mock.calls[0]
      expect(payload).toMatchObject({
        repoMode: 'workspace',
        workspaceRepos: ['git@github.com:org/repo.git'],
        gitOrigin: 'git@github.com:org/repo.git',
      })
    })

    it('(3) edit mode, monorepo with empty gitOrigin → click Workspace → one EMPTY Repo URL row (no pre-seed)', async () => {
      const editing = makeMockProject({
        gitOrigin: '',
        repoMode: 'monorepo',
        workspaceRepos: [],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      const repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields).toHaveLength(1)
      expect(repoFields[0]).toHaveValue('')
    })

    it('(4) edit mode, monorepo with gitOrigin AND pre-existing non-empty workspaceRepos → click Workspace → list unchanged', async () => {
      const editing = makeMockProject({
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'monorepo',
        workspaceRepos: ['git@github.com:org/other.git'],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      const repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields).toHaveLength(1)
      expect(repoFields[0]).toHaveValue('git@github.com:org/other.git')
    })

    it('(5) round-trip: monorepo with gitOrigin → Workspace (pre-seeds) → Monorepo → Workspace again → still one entry, not duplicated', async () => {
      const editing = makeMockProject({
        gitOrigin: 'git@github.com:org/repo.git',
        repoMode: 'monorepo',
        workspaceRepos: [],
        isOwner: true,
      })

      render(
        <ProjectEditDialog open={true} onClose={noop} editing={editing} onSaved={noop} />,
      )

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
      })

      // First: monorepo → workspace (pre-seeds)
      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      let repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields[0]).toHaveValue('git@github.com:org/repo.git')

      // Second: workspace → monorepo
      fireEvent.click(screen.getByRole('button', { name: 'Monorepo' }))

      await waitFor(() => {
        expect(screen.getByLabelText(/Git Origin/i)).toBeInTheDocument()
      })

      // Third: monorepo → workspace again (list already has the value, no duplication)
      fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))

      await waitFor(() => {
        expect(screen.queryByLabelText(/Git Origin/i)).not.toBeInTheDocument()
      })

      repoFields = screen.getAllByLabelText(/Repo URL/i)
      expect(repoFields).toHaveLength(1)
      expect(repoFields[0]).toHaveValue('git@github.com:org/repo.git')
    })
  })

})
