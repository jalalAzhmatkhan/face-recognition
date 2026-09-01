import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import EnrollmentDetailPage from './EnrollmentDetailPage'
import type { EnrollmentResponse } from '../features/enrollment-management/types'
import { CURRENT_CONSENT_VERSION } from '../features/enrollment-capture/types'

const { getCurrentRoleMock, getEnrollmentMock, grantConsentMock, startRecaptureMock, getUserMock } =
  vi.hoisted(() => ({
    getCurrentRoleMock: vi.fn(),
    getEnrollmentMock: vi.fn(),
    grantConsentMock: vi.fn(),
    startRecaptureMock: vi.fn(),
    getUserMock: vi.fn(),
  }))

vi.mock('../features/enrollment-management/authToken', () => ({
  getCurrentRole: getCurrentRoleMock,
}))

vi.mock('../features/enrollment-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/enrollment-management/api')>(
    '../features/enrollment-management/api',
  )
  return {
    ...actual,
    getEnrollment: getEnrollmentMock,
    grantConsent: grantConsentMock,
    startRecapture: startRecaptureMock,
  }
})

vi.mock('../features/user-management/api', async () => {
  const actual = await vi.importActual<typeof import('../features/user-management/api')>(
    '../features/user-management/api',
  )
  return { ...actual, getUser: getUserMock }
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

function renderPage(path = '/enrollments/session-1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/enrollments/:id" element={<EnrollmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

/** jsdom always reports `scrollHeight`/`clientHeight` as 0, which the
 * component reads as "content already fits, nothing to scroll" and
 * auto-enables the button immediately. Stub both BEFORE rendering to
 * simulate a real tall/not-yet-scrolled consent box for tests that need
 * to observe the "please scroll" disabled state. `scrollTop` is left as a
 * real, settable property so `fireEvent.scroll` behaves normally. */
function stubTallScrollBox() {
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(1000)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(240)
}

function NavigateOnClick({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(to)}>
      go
    </button>
  )
}

describe('EnrollmentDetailPage — consent flow', () => {
  it('shows the consent copywriting for the current consent version', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session())
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: 'EMP-1' })
    renderPage()

    expect((await screen.findAllByText(new RegExp(CURRENT_CONSENT_VERSION))).length).toBeGreaterThan(0)
    expect(
      screen.getByText(/Lepaskan masker dan/, { exact: false }),
    ).toBeInTheDocument()
  })

  it('never asks the operator to type a consent version', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session())
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    renderPage()

    await screen.findByRole('button', { name: `Catat Consent (${CURRENT_CONSENT_VERSION})` })
    expect(screen.queryByPlaceholderText(/versi/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('keeps "Catat Consent" disabled until the consent text is scrolled to the end', async () => {
    stubTallScrollBox()
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session())
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    renderPage()

    const button = await screen.findByRole('button', {
      name: `Catat Consent (${CURRENT_CONSENT_VERSION})`,
    })
    expect(button).toBeDisabled()

    const scrollBox = button.parentElement?.querySelector('div[style*="overflow"]') as HTMLDivElement
    fireEvent.scroll(scrollBox, { target: { scrollTop: 0 } })
    expect(button).toBeDisabled()

    // 760 + 240 (stubbed clientHeight) = 1000 (stubbed scrollHeight) -- fully scrolled.
    fireEvent.scroll(scrollBox, { target: { scrollTop: 760 } })
    expect(button).toBeEnabled()
  })

  it('auto-enables the button when the consent text is short enough to need no scrolling', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session())
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    renderPage()

    // jsdom's default scrollHeight/clientHeight are both 0 -- i.e. "content
    // already fits, nothing to scroll" -- so the button should already be
    // enabled without any scroll event at all.
    const button = await screen.findByRole('button', {
      name: `Catat Consent (${CURRENT_CONSENT_VERSION})`,
    })
    await waitFor(() => expect(button).toBeEnabled())
  })

  it('records consent with the current version automatically, without any manual input', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session())
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    grantConsentMock.mockResolvedValue(session({ state: 'CONSENTED' }))
    renderPage()

    const button = await screen.findByRole('button', {
      name: `Catat Consent (${CURRENT_CONSENT_VERSION})`,
    })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)

    await waitFor(() =>
      expect(grantConsentMock).toHaveBeenCalledWith('session-1', CURRENT_CONSENT_VERSION),
    )
  })

  it('resets the scroll-read state when navigating to a different session', async () => {
    stubTallScrollBox()
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    getEnrollmentMock.mockImplementation((id: string) => Promise.resolve(session({ id, user_id: 'user-1' })))

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/enrollments/session-1']}>
          <NavigateOnClick to="/enrollments/session-2" />
          <Routes>
            <Route path="/enrollments/:id" element={<EnrollmentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    let button = await screen.findByRole('button', {
      name: `Catat Consent (${CURRENT_CONSENT_VERSION})`,
    })
    const scrollBox = button.parentElement?.querySelector('div[style*="overflow"]') as HTMLDivElement
    fireEvent.scroll(scrollBox, { target: { scrollTop: 1000 } })
    expect(button).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: 'go' }))

    button = await screen.findByRole('button', { name: `Catat Consent (${CURRENT_CONSENT_VERSION})` })
    expect(button).toBeDisabled()
  })
})

describe('EnrollmentDetailPage — resume capture (CAPTURING recovery)', () => {
  function renderPageWithCaptureRoute(path = '/enrollments/session-1') {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/enrollments/:id" element={<EnrollmentDetailPage />} />
            <Route path="/enrollments/:id/capture" element={<p>CAPTURE_ROUTE</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('shows a resume-capture button (not the transition-triggering recapture button) when stuck in CAPTURING, and navigates straight into the wizard without calling startRecapture', async () => {
    getCurrentRoleMock.mockReturnValue('ADMIN')
    getEnrollmentMock.mockResolvedValue(session({ state: 'CAPTURING' }))
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: null })
    renderPageWithCaptureRoute()

    expect(await screen.findByText('Sedang Capture')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mulai / Ulangi Capture' })).not.toBeInTheDocument()

    const button = screen.getByRole('button', { name: /Lanjutkan.*Capture/i })
    fireEvent.click(button)

    expect(await screen.findByText('CAPTURE_ROUTE')).toBeInTheDocument()
    expect(startRecaptureMock).not.toHaveBeenCalled()
  })
})

describe('EnrollmentDetailPage — user name display', () => {
  it('shows the resolved user name instead of the raw user ID, linked to the user detail page', async () => {
    getCurrentRoleMock.mockReturnValue('VIEWER')
    getEnrollmentMock.mockResolvedValue(session({ state: 'ENROLLED' }))
    getUserMock.mockResolvedValue({ id: 'user-1', full_name: 'Budi Santoso', external_ref: 'EMP-1' })
    renderPage()

    const link = await screen.findByRole('link', { name: 'Budi Santoso' })
    expect(link).toHaveAttribute('href', '/users/user-1')
    expect(screen.queryByText('user-1')).not.toBeInTheDocument()
  })

  it('falls back to the raw user ID while the user lookup is still loading', async () => {
    getCurrentRoleMock.mockReturnValue('VIEWER')
    getEnrollmentMock.mockResolvedValue(session({ state: 'ENROLLED' }))
    getUserMock.mockImplementation(() => new Promise(() => {})) // never resolves
    renderPage()

    expect(await screen.findByText('user-1')).toBeInTheDocument()
  })
})
