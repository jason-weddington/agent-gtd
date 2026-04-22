import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Settings from '../pages/Settings'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('../api', () => ({
  api: {
    config: {
      get: vi.fn().mockResolvedValue({ localMode: false, version: '1.0.0' }),
    },
    dispatch: {
      capabilities: vi.fn(),
    },
    settings: {
      getMaxConcurrent: vi.fn().mockResolvedValue({ value: 6 }),
      setMaxConcurrent: vi.fn().mockResolvedValue({ value: 6 }),
      getDispatch: vi.fn(),
      updateDispatch: vi.fn(),
    },
    apiKeys: {
      list: vi.fn().mockResolvedValue({ keys: [] }),
    },
  },
  ApiError: class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
      this.detail = detail
    }
  },
}))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'test@example.com', createdAt: '2024-01-01' },
  }),
}))

vi.mock('../contexts/ThemeContext', () => ({
  useThemeMode: () => ({ mode: 'light' as const, toggleTheme: vi.fn() }),
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Import after mocks so we get the mocked version
async function getApi() {
  const mod = await import('../api')
  return mod.api
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Settings – Dispatch Service API Key field', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    // Default: configure api mock to return empty preview (no key stored)
    const api = await getApi()
    vi.mocked(api.settings.getDispatch).mockResolvedValue({
      engine: 'claude',
      agentName: '',
      maxConcurrent: 6,
      defaultMaxTurns: 100,
      serviceUrl: 'http://dispatch.example.com',
      serviceApiKeyPreview: '',
    })
    vi.mocked(api.settings.updateDispatch).mockResolvedValue({
      engine: 'claude',
      agentName: '',
      maxConcurrent: 6,
      defaultMaxTurns: 100,
      serviceUrl: 'http://dispatch.example.com',
      serviceApiKeyPreview: '****NEW1',
    })
    vi.mocked(api.dispatch.capabilities).mockResolvedValue({
      engine: 'claude-code',
      version: '1.2.3',
      agents: [
        { name: 'general-purpose', description: 'General purpose agent' },
      ],
    })
  })

  it('shows "Not configured" placeholder when serviceApiKeyPreview is empty', async () => {
    render(<Settings />)

    // The placeholder is visible from the very first render (state starts as '')
    // and remains after the API call resolves.
    const input = await screen.findByPlaceholderText('Not configured')
    expect(input).toBeInTheDocument()
    // Value stays empty (write-only field)
    expect(input).toHaveValue('')
  })

  it('shows the masked preview as placeholder when serviceApiKeyPreview is set', async () => {
    const api = await getApi()
    vi.mocked(api.settings.getDispatch).mockResolvedValue({
      engine: 'claude',
      agentName: '',
      maxConcurrent: 6,
      defaultMaxTurns: 100,
      serviceUrl: 'http://dispatch.example.com',
      serviceApiKeyPreview: '****jL54',
    })

    render(<Settings />)

    // After the API call resolves, placeholder should update to the preview
    const input = await screen.findByPlaceholderText('****jL54')
    expect(input).toBeInTheDocument()
    // Input value is still empty (never prefilled with the key)
    expect(input).toHaveValue('')
  })

  it('does NOT call updateDispatch when blurring an empty field', async () => {
    const api = await getApi()
    render(<Settings />)

    // Wait for initial load
    const input = await screen.findByPlaceholderText('Not configured')

    // Blur without typing anything
    fireEvent.blur(input)

    // No PATCH should have been sent
    expect(vi.mocked(api.settings.updateDispatch)).not.toHaveBeenCalled()
  })

  it('calls updateDispatch with typed value on blur, then clears the field', async () => {
    const api = await getApi()
    const user = userEvent.setup()

    render(<Settings />)

    const input = await screen.findByPlaceholderText('Not configured')

    // Type a new key
    await user.type(input, 'my-secret-api-key')
    expect(input).toHaveValue('my-secret-api-key')

    // Blur the field (move focus away)
    await user.tab()

    // updateDispatch should have been called with the typed value
    await waitFor(() => {
      expect(vi.mocked(api.settings.updateDispatch)).toHaveBeenCalledWith({
        serviceApiKey: 'my-secret-api-key',
      })
    })

    // After the save + reload, field should clear and placeholder updates
    await waitFor(() => {
      expect(input).toHaveValue('')
    })

    // Placeholder should now reflect the new preview returned by the API
    await waitFor(() => {
      expect(input).toHaveAttribute('placeholder', '****NEW1')
    })
  })
})
