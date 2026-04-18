import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import ShareTab from '../ShareTab'
import { api, ApiError } from '../../api'
import type { MemberSummary } from '../../types'

vi.mock('../../api', () => ({
  api: {
    projects: {
      members: {
        list: vi.fn(),
        add: vi.fn(),
        remove: vi.fn(),
      },
    },
  },
  ApiError: class extends Error {
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

const mockMembers: MemberSummary[] = [
  { userId: 'user-1', email: 'alice@example.com', addedAt: '2026-01-01T00:00:00Z' },
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.projects.members.list).mockResolvedValue([])
})

describe('ShareTab', () => {
  describe('owner view', () => {
    it('renders the add member form', async () => {
      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => {
        expect(screen.getByText('Share this project')).toBeInTheDocument()
      })
      expect(screen.getByLabelText(/Share with \(email address\)/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
    })

    it('shows "not shared with anyone" when member list is empty', async () => {
      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => {
        expect(screen.getByText(/Not shared with anyone yet/i)).toBeInTheDocument()
      })
    })

    it('lists existing members', async () => {
      vi.mocked(api.projects.members.list).mockResolvedValue(mockMembers)
      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => {
        expect(screen.getByText('alice@example.com')).toBeInTheDocument()
      })
    })

    it('shows 404 inline error when user is not found', async () => {
      vi.mocked(api.projects.members.list).mockResolvedValue([])
      vi.mocked(api.projects.members.add).mockRejectedValue(
        new ApiError(404, 'User not found'),
      )
      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())

      const input = screen.getByLabelText(/Share with \(email address\)/i)
      fireEvent.change(input, { target: { value: 'unknown@example.com' } })
      fireEvent.click(screen.getByRole('button', { name: /add/i }))

      await waitFor(() => {
        expect(screen.getByText(/user not found/i)).toBeInTheDocument()
      })
    })

    it('shows validation error on 422', async () => {
      vi.mocked(api.projects.members.list).mockResolvedValue([])
      vi.mocked(api.projects.members.add).mockRejectedValue(
        new ApiError(422, 'Invalid email address'),
      )
      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())

      const input = screen.getByLabelText(/Share with \(email address\)/i)
      fireEvent.change(input, { target: { value: 'bad-email' } })
      fireEvent.click(screen.getByRole('button', { name: /add/i }))

      await waitFor(() => {
        expect(screen.getByText(/Invalid email address/i)).toBeInTheDocument()
      })
    })

    it('clears the field and refreshes list on successful add', async () => {
      vi.mocked(api.projects.members.list).mockResolvedValue([])
      vi.mocked(api.projects.members.add).mockResolvedValue({
        userId: 'user-2',
        email: 'bob@example.com',
        addedAt: '2026-01-02T00:00:00Z',
      })
      // After add, the list refreshes with the new member
      vi.mocked(api.projects.members.list).mockResolvedValueOnce([]).mockResolvedValue([
        { userId: 'user-2', email: 'bob@example.com', addedAt: '2026-01-02T00:00:00Z' },
      ])

      render(<ShareTab projectId="proj-1" isOwner={true} />)
      await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())

      const input = screen.getByLabelText(/Share with \(email address\)/i)
      fireEvent.change(input, { target: { value: 'bob@example.com' } })
      fireEvent.click(screen.getByRole('button', { name: /add/i }))

      await waitFor(() => {
        expect(screen.getByText('bob@example.com')).toBeInTheDocument()
      })
      // Email field should be cleared
      expect(input).toHaveValue('')
    })
  })

  describe('member view (read-only)', () => {
    it('shows owner email when provided', async () => {
      render(
        <ShareTab
          projectId="proj-1"
          isOwner={false}
          ownerEmail="owner@example.com"
        />,
      )
      await waitFor(() => {
        expect(screen.getByText(/Shared by/i)).toBeInTheDocument()
        expect(screen.getByText('owner@example.com')).toBeInTheDocument()
      })
    })

    it('does not show the add form', async () => {
      render(
        <ShareTab projectId="proj-1" isOwner={false} ownerEmail="owner@example.com" />,
      )
      await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())
      expect(screen.queryByLabelText(/Share with/i)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument()
    })

    it('lists members without remove buttons', async () => {
      vi.mocked(api.projects.members.list).mockResolvedValue(mockMembers)
      render(
        <ShareTab projectId="proj-1" isOwner={false} ownerEmail="owner@example.com" />,
      )
      await waitFor(() => {
        expect(screen.getByText('alice@example.com')).toBeInTheDocument()
      })
      // No trash icon (delete button) in read-only view
      expect(screen.queryByTitle(/Remove member/i)).not.toBeInTheDocument()
    })
  })
})
