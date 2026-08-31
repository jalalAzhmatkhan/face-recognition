import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import SetupAdminPage from './SetupAdminPage'

const { getSetupStatusMock, bootstrapAdminMock, navigateMock } = vi.hoisted(() => ({
  getSetupStatusMock: vi.fn(),
  bootstrapAdminMock: vi.fn(),
  navigateMock: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../lib/authToken', async () => {
  const actual = await vi.importActual<typeof import('../lib/authToken')>('../lib/authToken')
  return {
    ...actual,
    getSetupStatus: getSetupStatusMock,
    bootstrapAdmin: bootstrapAdminMock,
  }
})

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SetupAdminPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('SetupAdminPage', () => {
  it('shows the create-admin form while setup is still needed', async () => {
    getSetupStatusMock.mockResolvedValue({ needs_setup: true })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Setup Awal FRAC Console' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Buat Akun ADMIN' })).toBeInTheDocument()
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('redirects to /login once an ADMIN already exists', async () => {
    getSetupStatusMock.mockResolvedValue({ needs_setup: false })
    renderPage()

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true }))
    expect(screen.queryByRole('heading', { name: 'Setup Awal FRAC Console' })).not.toBeInTheDocument()
  })

  it('redirects to /login if the setup-status check fails', async () => {
    getSetupStatusMock.mockRejectedValue(new Error('network down'))
    renderPage()

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true }))
  })

  it('submits email+password and navigates to / on success', async () => {
    getSetupStatusMock.mockResolvedValue({ needs_setup: true })
    bootstrapAdminMock.mockResolvedValue(undefined)
    renderPage()

    await screen.findByRole('heading', { name: 'Setup Awal FRAC Console' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'admin@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'S0meStrongPass!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buat Akun ADMIN' }))

    await waitFor(() =>
      expect(bootstrapAdminMock).toHaveBeenCalledWith({
        email: 'admin@example.com',
        password: 'S0meStrongPass!',
      }),
    )
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/', { replace: true }))
  })

  it('shows an error message when bootstrap fails', async () => {
    const { BootstrapAdminError } = await import('../lib/authToken')
    getSetupStatusMock.mockResolvedValue({ needs_setup: true })
    bootstrapAdminMock.mockRejectedValue(
      new BootstrapAdminError('Akun ADMIN sudah pernah dibuat sebelumnya.', 409),
    )
    renderPage()

    await screen.findByRole('heading', { name: 'Setup Awal FRAC Console' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'admin@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'S0meStrongPass!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buat Akun ADMIN' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Akun ADMIN sudah pernah dibuat sebelumnya.',
    )
    expect(navigateMock).not.toHaveBeenCalledWith('/', { replace: true })
  })
})
