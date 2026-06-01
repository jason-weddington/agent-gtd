import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Settings from '../pages/Settings'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('../api', () => ({
  api: {
    auth: {
      changePassword: vi.fn(),
    },
    config: {
      get: vi.fn().mockResolvedValue({ localMode: false, version: '1.0.0' }),
    },
    dispatch: {
      capabilities: vi.fn(),
    },
    dispatchHosts: {
      list: vi.fn(),
      add: vi.fn(),
      remove: vi.fn(),
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

describe('Settings – Dispatch Hosts', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const api = await getApi()

    vi.mocked(api.dispatchHosts.list).mockResolvedValue([])
    vi.mocked(api.dispatchHosts.add).mockResolvedValue({
      id: 'host-1',
      label: 'my-host',
      url: 'http://dispatch.example.com',
      apiKeyPreview: '****key1',
      createdAt: '2024-01-01T00:00:00Z',
    })
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
    vi.mocked(api.settings.updateDispatch).mockResolvedValue({
      engine: 'claude-code',
      planAgentName: '',
      buildAgentName: '',
      defaultMaxTurns: 100,
      defaultTimeoutMinutes: 90,
      managerDefaultTimeoutMinutes: 240,
      serviceUrl: '',
      serviceApiKeyPreview: '',
    })
    vi.mocked(api.dispatch.capabilities).mockResolvedValue({
      engines: ['claude-code'],
      versions: ['1.2.3'],
      agents: [
        { name: 'general-purpose', description: 'General purpose agent' },
      ],
      totalCapacity: 32,
    })
  })

  it('renders "Add Dispatch Host" form with URL and API Key fields', async () => {
    render(<Settings />)

    expect(await screen.findByText('Add Dispatch Host')).toBeInTheDocument()
    expect(screen.getByLabelText(/URL/)).toBeInTheDocument()
    expect(screen.getByLabelText(/API Key/)).toBeInTheDocument()
  })

  it('shows configured hosts returned by the API', async () => {
    const api = await getApi()
    vi.mocked(api.dispatchHosts.list).mockResolvedValue([
      {
        id: 'h1',
        label: 'pi-1',
        url: 'http://pi1.local:8001',
        apiKeyPreview: '****abcd',
        createdAt: '2024-01-01T00:00:00Z',
      },
    ])

    render(<Settings />)

    // The host primary text (label) should appear
    expect(await screen.findByText('pi-1')).toBeInTheDocument()
  })

  it('Add Host button is disabled when URL is empty', async () => {
    render(<Settings />)

    await screen.findByText('Add Dispatch Host')
    const addBtn = screen.getByRole('button', { name: /Add Host/i })
    expect(addBtn).toBeDisabled()
  })

  it('Add Host button is disabled when API Key is empty but URL is filled', async () => {
    render(<Settings />)

    await screen.findByText('Add Dispatch Host')
    // Use placeholder to locate URL input unambiguously
    const urlInput = screen.getByPlaceholderText('https://dispatch.example.com')
    fireEvent.change(urlInput, { target: { value: 'http://dispatch.local:8001' } })

    const addBtn = screen.getByRole('button', { name: /Add Host/i })
    expect(addBtn).toBeDisabled()
  })

  it('calls dispatchHosts.add with label, url, and api_key on submit', async () => {
    const api = await getApi()

    render(<Settings />)

    // Wait for the dispatch section to appear
    const addHostHeading = await screen.findByText('Add Dispatch Host')
    expect(addHostHeading).toBeInTheDocument()

    const urlInput = screen.getByPlaceholderText('https://dispatch.example.com')
    fireEvent.change(urlInput, { target: { value: 'http://dispatch.local:8001' } })

    // The API Key password field is the last input in the Add Host form.
    // Use getAllByDisplayValue to avoid ambiguity — or locate by querying inputs near the button.
    // The Add Host form has exactly 3 TextFields: Label (optional), URL, API Key.
    // We can locate the password input directly since it's the only type="password" in that form.
    const addHostBtn = screen.getByRole('button', { name: /Add Host/i })
    // Get all password inputs — the last is the API Key (add-host form);
    // any earlier ones belong to the change-password section.
    const passwordInputs = document.querySelectorAll('input[type="password"]')
    // The last password input is the API Key (add-host form) — others are in change-password
    const apiKeyInput = passwordInputs[passwordInputs.length - 1] as HTMLElement
    fireEvent.change(apiKeyInput, { target: { value: 'secret-key' } })

    expect(addHostBtn).toBeEnabled()
    fireEvent.click(addHostBtn)

    await waitFor(() => {
      expect(vi.mocked(api.dispatchHosts.add)).toHaveBeenCalledWith(
        '',
        'http://dispatch.local:8001',
        'secret-key',
      )
    })
  })

  it('reloads host list after adding a host', async () => {
    const api = await getApi()

    render(<Settings />)

    await screen.findByText('Add Dispatch Host')

    fireEvent.change(
      screen.getByPlaceholderText('https://dispatch.example.com'),
      { target: { value: 'http://dispatch.local:8001' } },
    )
    const passwordInputs = document.querySelectorAll('input[type="password"]')
    const apiKeyInput = passwordInputs[passwordInputs.length - 1] as HTMLElement
    fireEvent.change(apiKeyInput, { target: { value: 'secret-key' } })
    fireEvent.click(screen.getByRole('button', { name: /Add Host/i }))

    await waitFor(() => {
      // list should be called again after add
      expect(vi.mocked(api.dispatchHosts.list).mock.calls.length).toBeGreaterThan(1)
    })
  })

  it('renders both "Worker timeout (min)" and "Manager timeout (min)" labels in Agent Dispatch card', async () => {
    render(<Settings />)

    expect(await screen.findByLabelText(/Worker timeout \(min\)/)).toBeInTheDocument()
    expect(await screen.findByLabelText(/Manager timeout \(min\)/)).toBeInTheDocument()
  })

  it('calls updateDispatch with managerDefaultTimeoutMinutes when manager timeout input blurs', async () => {
    const api = await getApi()

    render(<Settings />)

    const managerTimeoutInput = await screen.findByLabelText(/Manager timeout \(min\)/)
    fireEvent.change(managerTimeoutInput, { target: { value: '300' } })
    fireEvent.blur(managerTimeoutInput)

    await waitFor(() => {
      expect(vi.mocked(api.settings.updateDispatch)).toHaveBeenCalledWith(
        expect.objectContaining({ managerDefaultTimeoutMinutes: 300 }),
      )
    })
  })
})
