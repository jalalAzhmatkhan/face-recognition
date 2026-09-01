import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UsersPage from './UsersPage'
import type { UserResponse } from '../features/user-management/types'

const { getCurrentRoleMock, listUsersMock, createEnrollmentMock } = vi.hoisted(() => ({
  getCurrentRoleMock: vi.fn(),
  listUsersMock: vi.fn(),
  createEnrollmentMock: vi.fn(),
}))

vi.mock('../lib/authToken', () => ({
  getCurrentRole: getCurrentRoleMock,
}))

vi.mock('../features/user-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/user-management/api')>(
    '../features/user-management/api',
  )
  return {
    ...actual,
    listUsers: listUsersMock,
  }
})

vi.mock('../features/enrollment-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/enrollment-management/api')>(
    '../features/enrollment-management/api',
  )
  return {
    ...actual,
    createEnrollment: createEnrollmentMock,
  }
})

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
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('UsersPage — reenroll_due badge (EC-FE-03)', () => {
  it('shows the "Perlu Re-enroll" badge for a user flagged reenroll_due', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    listUsersMock.mockResolvedValue({
      items: [user({ reenroll_due: true, reenroll_due_reason: 'low_genuine_score' })],
      total: 1,
      limit: 20,
      offset: 0,
    })
    renderPage()
    expect(await screen.findByText('Budi Santoso')).toBeInTheDocument()
    expect(screen.getByText('Perlu Re-enroll')).toBeInTheDocument()
  })

  it('does not show the badge for a user without reenroll_due (or when the field is absent, matching today\'s real API response)', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    listUsersMock.mockResolvedValue({ items: [user()], total: 1, limit: 20, offset: 0 })
    renderPage()
    expect(await screen.findByText('Budi Santoso')).toBeInTheDocument()
    expect(screen.queryByText('Perlu Re-enroll')).not.toBeInTheDocument()
  })

  it('labels the enrollment action "Mulai Re-enroll" instead of "Mulai Enrollment" when due', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    listUsersMock.mockResolvedValue({
      items: [user({ reenroll_due: true })],
      total: 1,
      limit: 20,
      offset: 0,
    })
    renderPage()
    await screen.findByText('Budi Santoso')

    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    expect(screen.getByRole('menuitem', { name: 'Mulai Re-enroll' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Mulai Enrollment' })).not.toBeInTheDocument()
  })

  it('the re-enroll action reuses the existing enrollment wizard (same createEnrollment call, same navigation)', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    listUsersMock.mockResolvedValue({
      items: [user({ id: 'user-9', reenroll_due: true })],
      total: 1,
      limit: 20,
      offset: 0,
    })
    createEnrollmentMock.mockResolvedValue({ id: 'session-42' })
    renderPage()
    await screen.findByText('Budi Santoso')

    fireEvent.click(screen.getByRole('button', { name: 'Aksi lainnya' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Mulai Re-enroll' }))

    await waitFor(() => expect(createEnrollmentMock).toHaveBeenCalledWith('user-9'))
  })
})
