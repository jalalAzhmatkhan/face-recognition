import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import EnrollmentsPage from './EnrollmentsPage'
import type { EnrollmentResponse } from '../features/enrollment-management/types'
import type { UserResponse } from '../features/user-management/types'

const { getCurrentRoleMock, listEnrollmentsMock, listUsersMock } = vi.hoisted(() => ({
  getCurrentRoleMock: vi.fn(),
  listEnrollmentsMock: vi.fn(),
  listUsersMock: vi.fn(),
}))

vi.mock('../features/enrollment-management/authToken', () => ({
  getCurrentRole: getCurrentRoleMock,
}))

vi.mock('../features/enrollment-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/enrollment-management/api')>(
    '../features/enrollment-management/api',
  )
  return { ...actual, listEnrollments: listEnrollmentsMock }
})

vi.mock('../features/user-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/user-management/api')>(
    '../features/user-management/api',
  )
  return { ...actual, listUsers: listUsersMock }
})

function session(overrides: Partial<EnrollmentResponse> = {}): EnrollmentResponse {
  return {
    id: 'session-1',
    user_id: 'user-1',
    state: 'CREATED',
    qc_report: null,
    created_by: 'staff-1',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function user(overrides: Partial<UserResponse> = {}): UserResponse {
  return {
    id: 'user-1',
    external_ref: 'EMP-001',
    full_name: 'Budi Santoso',
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <EnrollmentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('EnrollmentsPage — user name column', () => {
  it('shows the resolved user name (with external_ref) instead of the raw user ID, linked to the user detail page', async () => {
    getCurrentRoleMock.mockReturnValue('VIEWER')
    listEnrollmentsMock.mockResolvedValue({ items: [session()], total: 1, limit: 20, offset: 0 })
    listUsersMock.mockResolvedValue({ items: [user()], total: 1, limit: 200, offset: 0 })
    renderPage()

    const link = await screen.findByRole('link', { name: 'Budi Santoso (EMP-001)' })
    expect(link).toHaveAttribute('href', '/users/user-1')
    expect(screen.queryByText('user-1')).not.toBeInTheDocument()
  })

  it('falls back to the raw user ID when the user is not found in the lookup', async () => {
    getCurrentRoleMock.mockReturnValue('VIEWER')
    listEnrollmentsMock.mockResolvedValue({
      items: [session({ user_id: 'ghost-user' })],
      total: 1,
      limit: 20,
      offset: 0,
    })
    listUsersMock.mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 })
    renderPage()

    expect(await screen.findByText('ghost-user')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /ghost-user/ })).not.toBeInTheDocument()
  })
})
