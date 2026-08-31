import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DevicesPage from './DevicesPage'
import type { DeviceResponse } from '../features/device-management/types'

const {
  getCurrentRoleMock,
  listDevicesMock,
  createDeviceMock,
  rotateDeviceCredentialMock,
  sendDeviceHeartbeatMock,
} = vi.hoisted(() => ({
  getCurrentRoleMock: vi.fn(),
  listDevicesMock: vi.fn(),
  createDeviceMock: vi.fn(),
  rotateDeviceCredentialMock: vi.fn(),
  sendDeviceHeartbeatMock: vi.fn(),
}))

vi.mock('../lib/authToken', () => ({
  getCurrentRole: getCurrentRoleMock,
}))

vi.mock('../features/device-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/device-management/api')>(
    '../features/device-management/api',
  )
  return {
    ...actual,
    listDevices: listDevicesMock,
    createDevice: createDeviceMock,
    rotateDeviceCredential: rotateDeviceCredentialMock,
    sendDeviceHeartbeat: sendDeviceHeartbeatMock,
  }
})

function device(overrides: Partial<DeviceResponse> = {}): DeviceResponse {
  return {
    id: 'device-1',
    name: 'Pintu Lobby',
    door_group: 'lobby',
    status: 'ONLINE',
    last_heartbeat_at: '2026-08-30T08:00:00Z',
    credential_rotated_at: '2026-08-01T00:00:00Z',
    is_stale: false,
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <DevicesPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  listDevicesMock.mockResolvedValue({ items: [device()], total: 1, limit: 20, offset: 0 })
})

describe('DevicesPage — role gating', () => {
  it('renders the device table for ADMIN', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    renderPage()
    expect(await screen.findByText('Pintu Lobby')).toBeInTheDocument()
    expect(screen.getByText('lobby')).toBeInTheDocument()
  })

  it('renders the device table for OPERATOR', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    renderPage()
    expect(await screen.findByText('Pintu Lobby')).toBeInTheDocument()
  })

  it('shows a clear "no access" message for VIEWER instead of a table', async () => {
    getCurrentRoleMock.mockReturnValue('VIEWER')
    renderPage()
    expect(await screen.findByText('Tidak Ada Akses')).toBeInTheDocument()
    expect(screen.queryByText('Pintu Lobby')).not.toBeInTheDocument()
    // VIEWER must never even trigger the request (READ_ROLES excludes it).
    expect(listDevicesMock).not.toHaveBeenCalled()
  })

  it('shows the "no access" message for an unauthenticated session too', async () => {
    getCurrentRoleMock.mockReturnValue(null)
    renderPage()
    expect(await screen.findByText('Tidak Ada Akses')).toBeInTheDocument()
  })
})

describe('DevicesPage — write-role gating', () => {
  it('shows "Tambah Device" for ADMIN', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    renderPage()
    await screen.findByText('Pintu Lobby')
    expect(screen.getByRole('button', { name: 'Tambah Device' })).toBeInTheDocument()
  })

  it('hides "Tambah Device" entirely for OPERATOR (not merely disabled)', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    renderPage()
    await screen.findByText('Pintu Lobby')
    expect(screen.queryByRole('button', { name: 'Tambah Device' })).not.toBeInTheDocument()
    // OPERATOR has none of Edit/Rotate/Disable -- the whole "⋮" actions
    // trigger is absent for this row, not just disabled or empty when opened.
    expect(screen.queryByRole('button', { name: 'Aksi lainnya' })).not.toBeInTheDocument()
  })
})

describe('DevicesPage — credential bootstrap dialog', () => {
  it('shows the credential dialog after a successful create, closable only via the explicit button', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    createDeviceMock.mockResolvedValue({ ...device({ id: 'device-2' }), credential: 'boot-cred-1' })
    renderPage()
    await screen.findByText('Pintu Lobby')

    fireEvent.click(screen.getByRole('button', { name: 'Tambah Device' }))
    fireEvent.change(screen.getByPlaceholderText('Nama Device (mis. Pintu Lobby)'), {
      target: { value: 'Pintu Gudang' },
    })
    fireEvent.change(screen.getByPlaceholderText('Door Group (mis. lobby)'), {
      target: { value: 'gudang' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan Device' }))

    expect(await screen.findByTestId('credential-value')).toHaveTextContent('boot-cred-1')
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()

    // No close-on-overlay-click / ESC affordance: only the explicit
    // acknowledge button removes the dialog.
    const ackButton = screen.getByRole('button', {
      name: 'Saya sudah menyimpan kredensial ini',
    })
    fireEvent.click(ackButton)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('shows the credential dialog again after a successful credential rotation', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    rotateDeviceCredentialMock.mockResolvedValue({ ...device(), credential: 'new-cred-2' })
    renderPage()
    await screen.findByText('Pintu Lobby')

    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rotasi Kredensial' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ya, Rotasi' }))

    expect(await screen.findByTestId('credential-value')).toHaveTextContent('new-cred-2')
  })
})

describe('DevicesPage — device activation dialog', () => {
  it('sends a heartbeat with the pasted credential and shows the result', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    sendDeviceHeartbeatMock.mockResolvedValue({
      status: 'ONLINE',
      last_heartbeat_at: '2026-08-31T00:00:00Z',
    })
    renderPage()
    await screen.findByText('Pintu Lobby')

    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Aktivasi (Simulasi Heartbeat)' }))

    expect(screen.getByRole('dialog')).toHaveTextContent('Aktivasi Device: Pintu Lobby')

    fireEvent.change(screen.getByPlaceholderText('credential_id.secret'), {
      target: { value: 'cred-1.secret-1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Mulai Heartbeat' }))

    await waitFor(() =>
      expect(sendDeviceHeartbeatMock).toHaveBeenCalledWith('device-1', 'cred-1.secret-1'),
    )
    expect(await screen.findByText(/Heartbeat berjalan/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(screen.getByText(/Heartbeat dihentikan/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Tutup' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not show the "Aktivasi" action for OPERATOR', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    renderPage()
    await screen.findByText('Pintu Lobby')
    expect(screen.queryByRole('button', { name: 'Aksi lainnya' })).not.toBeInTheDocument()
  })
})
