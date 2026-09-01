import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UserDetailPage from './UserDetailPage'
import type { UserResponse } from '../features/user-management/types'

const { getCurrentRoleMock, getUserMock, createEnrollmentMock } = vi.hoisted(() => ({
  getCurrentRoleMock: vi.fn(),
  getUserMock: vi.fn(),
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
    getUser: getUserMock,
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
      <MemoryRouter initialEntries={['/users/user-1']}>
        <Routes>
          <Route path="/users/:id" element={<UserDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('UserDetailPage — reenroll_due (EC-FE-03)', () => {
  it('shows the badge and reason when the user is flagged reenroll_due', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    getUserMock.mockResolvedValue(
      user({ reenroll_due: true, reenroll_due_reason: 'enrollment_older_than_24_months' }),
    )
    renderPage()
    expect(await screen.findByText('Perlu Re-enroll')).toBeInTheDocument()
    expect(screen.getByText('Alasan: enrollment_older_than_24_months')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mulai Re-enroll' })).toBeInTheDocument()
  })

  it('shows plain "Mulai Enrollment" and no badge when reenroll_due is absent (real backend shape today)', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    getUserMock.mockResolvedValue(user())
    renderPage()
    await screen.findByText('Informasi User')
    expect(screen.queryByText('Perlu Re-enroll')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mulai Enrollment' })).toBeInTheDocument()
  })

  it('re-enroll button reuses the existing enrollment wizard', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    getUserMock.mockResolvedValue(user({ reenroll_due: true }))
    createEnrollmentMock.mockResolvedValue({ id: 'session-7' })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Mulai Re-enroll' }))
    await waitFor(() => expect(createEnrollmentMock).toHaveBeenCalledWith('user-1'))
  })
})

describe('UserDetailPage — identity_similarity_flags (ADMIN-only, EC-FE-03)', () => {
  it('shows the similarity panel placeholder for ADMIN', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getUserMock.mockResolvedValue(user())
    renderPage()
    expect(await screen.findByText('Pasangan High-Similarity')).toBeInTheDocument()
    expect(screen.getByText(/Menunggu endpoint backend/)).toBeInTheDocument()
  })

  it('hides the similarity panel entirely for OPERATOR and VIEWER', async () => {
    getCurrentRoleMock.mockReturnValue('OPERATOR')
    getUserMock.mockResolvedValue(user())
    renderPage()
    await screen.findByText('Informasi User')
    expect(screen.queryByText('Pasangan High-Similarity')).not.toBeInTheDocument()
  })
})
