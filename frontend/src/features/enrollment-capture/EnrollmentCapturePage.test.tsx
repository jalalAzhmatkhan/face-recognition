import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import EnrollmentCapturePage from './EnrollmentCapturePage'
import * as apiClient from './apiClient'

afterEach(() => cleanup())

const ACCESS_TOKEN_KEY = 'frac_access_token'

function renderPage(enrollmentId = 'session-123') {
  return render(
    <MemoryRouter initialEntries={[`/enrollments/${enrollmentId}/capture`]}>
      <Routes>
        <Route path="/enrollments/:id/capture" element={<EnrollmentCapturePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('EnrollmentCapturePage — EC-FE-02 matched-condition + preflight', () => {
  beforeEach(() => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  })

  it('shows the matched-condition instruction text on the consent step', () => {
    renderPage()

    expect(
      screen.getByText(/Tampil seperti Anda datang bekerja sehari-hari/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Lepaskan masker dan/)).toBeInTheDocument()
    expect(
      screen.getAllByText(/kacamata hitam \(sunglasses\)/).length,
    ).toBeGreaterThan(0)
  })

  it('disables "Saya Setuju & Mulai" until the confirmation checkbox is checked', () => {
    renderPage()

    const startButton = screen.getByRole('button', { name: /Saya Setuju & Mulai/ })
    const checkbox = screen.getByRole('checkbox', {
      name: /saya sudah melepas masker dan kacamata hitam/i,
    })

    expect(startButton).toBeDisabled()
    expect(checkbox).not.toBeChecked()

    fireEvent.click(checkbox)

    expect(checkbox).toBeChecked()
    expect(startButton).toBeEnabled()
  })

  it('re-disables the start button if the checkbox is unchecked again', () => {
    renderPage()

    const startButton = screen.getByRole('button', { name: /Saya Setuju & Mulai/ })
    const checkbox = screen.getByRole('checkbox', {
      name: /saya sudah melepas masker dan kacamata hitam/i,
    })

    fireEvent.click(checkbox)
    expect(startButton).toBeEnabled()

    fireEvent.click(checkbox)
    expect(startButton).toBeDisabled()
  })

  it('blocks getUserMedia (camera start) from ever being invoked without confirmation', () => {
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [],
    })
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })

    renderPage()

    const startButton = screen.getByRole('button', { name: /Saya Setuju & Mulai/ })
    // Clicking a disabled button must not trigger the click handler.
    fireEvent.click(startButton)
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('shows a login prompt instead of the wizard when unauthenticated', () => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent(/perlu login/i)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})

describe('EnrollmentCapturePage — EC-FE-05 consent text + consent_version submission', () => {
  beforeEach(() => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'test-token')
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }),
      },
      configurable: true,
    })
  })

  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    vi.restoreAllMocks()
  })

  function agreeAndStart() {
    const checkbox = screen.getByRole('checkbox', {
      name: /saya sudah melepas masker dan kacamata hitam/i,
    })
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole('button', { name: /Saya Setuju & Mulai/ }))
  }

  it('shows the three new ASM-EC-05 consent clauses on the consent step', () => {
    renderPage()

    expect(screen.getByText(/template wajah sintetis/i)).toBeInTheDocument()
    expect(screen.getByText(/kamera pintu\/absensi/i)).toBeInTheDocument()
    expect(
      screen.getByText(/memperbarui\/menyegarkan profil wajah Anda secara/i),
    ).toBeInTheDocument()
  })

  it('sends consent_version="v1.1" (CURRENT_CONSENT_VERSION) when agreeing and starting', async () => {
    const grantConsentSpy = vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({
      id: 'session-123',
      state: 'CONSENTED',
    })

    renderPage('session-123')
    agreeAndStart()

    await waitFor(() => expect(grantConsentSpy).toHaveBeenCalledWith('session-123', 'v1.1'))
  })

  it('attaches the acquired camera stream to the <video> element once the preflight step mounts (regression: the <video> element does not exist yet while still on the consent step, so assigning srcObject at that point was silently a no-op and the screen stayed blank)', async () => {
    const fakeStream = { getTracks: () => [] } as unknown as MediaStream
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream)
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })
    vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({ id: 'session-123', state: 'CONSENTED' })

    const { container } = renderPage('session-123')
    agreeAndStart()

    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    await waitFor(() => {
      const video = container.querySelector('video')
      expect(video?.srcObject).toBe(fakeStream)
    })
  })

  it('still starts the camera even if the best-effort consent grant fails (e.g. already consented)', async () => {
    const grantConsentSpy = vi
      .spyOn(apiClient, 'grantConsent')
      .mockRejectedValue(new apiClient.ApiError('conflict', 409, null))
    const getUserMedia = window.navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>

    renderPage('session-123')
    agreeAndStart()

    await waitFor(() => expect(grantConsentSpy).toHaveBeenCalled())
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
  })
})
