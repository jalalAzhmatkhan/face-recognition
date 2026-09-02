import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import EnrollmentCapturePage from './EnrollmentCapturePage'
import * as apiClient from './apiClient'

afterEach(() => cleanup())

const ACCESS_TOKEN_KEY = 'frac_access_token'

/**
 * Storage is emptied before every test by `src/setupTests.ts`, so each suite
 * only has to say what it needs PRESENT — nothing here deletes the token on
 * the way out. Cleaning up forward rather than backward matters, because
 * `afterEach` hooks run innermost-first: a suite-level
 * `removeItem(ACCESS_TOKEN_KEY)` fired while the finished test's tree was
 * still mounted (only the file-level `cleanup()` unmounts it, and that runs
 * afterwards).
 */
function signIn() {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, 'test-token')
}

/**
 * Stub the two calls this page fires on mount, for EVERY test in this file.
 *
 * This is not tidiness — it is the fix for a cross-test flake. Both go
 * through `apiClient.authFetch`, and a test that left them unstubbed issued a
 * REAL request into jsdom, which comes back 401. `authFetch` answers a 401 by
 * calling `refreshAccessToken()`, which finds no refresh token and runs
 * `clearTokens()` — deleting `frac_access_token` (lib/authToken.ts:63).
 *
 * Nothing awaits that chain: the mount effect ends in `.catch(() => {})`, so
 * the request outlives the test that started it. On a contended worker it
 * settled during a LATER test and logged that test out mid-flight, which is
 * why the page intermittently rendered its "Anda perlu login" branch in
 * full-suite runs only, and never on its own. It was previously worked
 * around by spying on `getAccessToken` in the affected test, which hid the
 * wiped token instead of preventing it.
 *
 * A test that cares about either call still spies on it directly; those spies
 * replace these (`restoreMocks` in vite.config.ts resets between tests).
 */
function stubMountRequests() {
  vi.spyOn(apiClient, 'getEnrollmentQualityParams').mockResolvedValue({
    min_blur_variance: 60,
    min_brightness: 60,
    max_brightness: 200,
  })
  vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({
    id: 'session-123',
    state: 'CONSENTED',
  })
}

beforeEach(stubMountRequests)

/**
 * `navigator.mediaDevices` does not exist in jsdom, so it has to be defined
 * rather than spied — which means `restoreMocks` cannot undo it. Restoring it
 * explicitly keeps a camera stub from leaking into a suite that never asked
 * for one (previously whichever suite defined it last won for the rest of the
 * file).
 */
const mediaDevicesDescriptor = Object.getOwnPropertyDescriptor(
  window.navigator,
  'mediaDevices',
)

function stubMediaDevices(getUserMedia: ReturnType<typeof vi.fn>) {
  Object.defineProperty(window.navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
  })
  return getUserMedia
}

afterEach(() => {
  if (mediaDevicesDescriptor) {
    Object.defineProperty(window.navigator, 'mediaDevices', mediaDevicesDescriptor)
  } else {
    Reflect.deleteProperty(window.navigator, 'mediaDevices')
  }
})

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
  beforeEach(signIn)

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
    const getUserMedia = stubMediaDevices(
      vi.fn().mockResolvedValue({ getTracks: () => [] }),
    )

    renderPage()

    const startButton = screen.getByRole('button', { name: /Saya Setuju & Mulai/ })
    // Clicking a disabled button must not trigger the click handler.
    fireEvent.click(startButton)
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('shows a login prompt instead of the wizard when unauthenticated', () => {
    // The one test that genuinely wants no token, so it clears the one this
    // suite's beforeEach just set.
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent(/perlu login/i)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})

describe('EnrollmentCapturePage — EC-FE-05 consent text + consent_version submission', () => {
  beforeEach(() => {
    signIn()
    stubMediaDevices(vi.fn().mockResolvedValue({ getTracks: () => [] }))
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

  it('sends consent_version="v1.2" (CURRENT_CONSENT_VERSION) when agreeing and starting', async () => {
    const grantConsentSpy = vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({
      id: 'session-123',
      state: 'CONSENTED',
    })

    renderPage('session-123')
    agreeAndStart()

    await waitFor(() => expect(grantConsentSpy).toHaveBeenCalledWith('session-123', 'v1.2'))
  })

  it('attaches the acquired camera stream to the <video> element once the preflight step mounts (regression: the <video> element does not exist yet while still on the consent step, so assigning srcObject at that point was silently a no-op and the screen stayed blank)', async () => {
    const fakeStream = { getTracks: () => [] } as unknown as MediaStream
    const getUserMedia = stubMediaDevices(vi.fn().mockResolvedValue(fakeStream))
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

describe('EnrollmentCapturePage — "Batal" discards capture and returns to Enrollment list', () => {
  beforeEach(signIn)

  function renderPageWithEnrollmentsRoute(enrollmentId = 'session-123') {
    return render(
      <MemoryRouter initialEntries={[`/enrollments/${enrollmentId}/capture`]}>
        <Routes>
          <Route path="/enrollments/:id/capture" element={<EnrollmentCapturePage />} />
          <Route path="/enrollments" element={<p>ENROLLMENTS_LIST</p>} />
        </Routes>
      </MemoryRouter>,
    )
  }

  function agreeAndStart() {
    const checkbox = screen.getByRole('checkbox', {
      name: /saya sudah melepas masker dan kacamata hitam/i,
    })
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole('button', { name: /Saya Setuju & Mulai/ }))
  }

  it('shows a "Batal" button on the frontal-photo (preflight) step that stops the camera and navigates to /enrollments after confirmation', async () => {
    const stopTrack = vi.fn()
    const fakeStream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
    stubMediaDevices(vi.fn().mockResolvedValue(fakeStream))
    vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({ id: 'session-123', state: 'CONSENTED' })
    vi.spyOn(apiClient, 'getEnrollmentQualityParams').mockResolvedValue({
      min_blur_variance: 30,
      min_brightness: 35,
      max_brightness: 225,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderPageWithEnrollmentsRoute()
    agreeAndStart()

    const cancelButton = await screen.findByRole('button', { name: 'Batal' })
    fireEvent.click(cancelButton)

    expect(window.confirm).toHaveBeenCalled()
    expect(stopTrack).toHaveBeenCalled()
    expect(await screen.findByText('ENROLLMENTS_LIST')).toBeInTheDocument()
  })

  it('does nothing when the confirmation dialog is dismissed', async () => {
    stubMediaDevices(
      vi.fn().mockResolvedValue({ getTracks: () => [] } as unknown as MediaStream),
    )
    vi.spyOn(apiClient, 'grantConsent').mockResolvedValue({ id: 'session-123', state: 'CONSENTED' })
    vi.spyOn(apiClient, 'getEnrollmentQualityParams').mockResolvedValue({
      min_blur_variance: 30,
      min_brightness: 35,
      max_brightness: 225,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderPageWithEnrollmentsRoute()
    agreeAndStart()

    const cancelButton = await screen.findByRole('button', { name: 'Batal' })
    fireEvent.click(cancelButton)

    expect(window.confirm).toHaveBeenCalled()
    expect(screen.queryByText('ENROLLMENTS_LIST')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Ambil Foto Frontal' })).toBeInTheDocument()
  })
})

describe('EnrollmentCapturePage — System Parameter quality threshold override', () => {
  beforeEach(signIn)

  it('fetches the current enrollment-quality System Parameter on mount', async () => {
    const spy = vi.spyOn(apiClient, 'getEnrollmentQualityParams').mockResolvedValue({
      min_blur_variance: 30,
      min_brightness: 35,
      max_brightness: 225,
    })

    renderPage()

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(spy).toHaveResolved())
  })

  it('never blocks the wizard when the System Parameter fetch fails (falls back to built-in defaults)', () => {
    vi.spyOn(apiClient, 'getEnrollmentQualityParams').mockRejectedValue(new Error('network'))

    renderPage()

    // `getByRole`, not `findByRole`. The consent step is rendered
    // SYNCHRONOUSLY by `render()` -- there is nothing to wait for, and the
    // point of the test is precisely that the failing fetch never gates it.
    // Awaiting it anyway put the assertion behind Testing Library's 1000 ms
    // deadline, which on a contended worker (measured: 700-1500 ms for steps
    // that take ~10 ms standalone) is a coin flip that has nothing to do
    // with the component. Every other assertion on this same button in this
    // file already uses the synchronous query.
    expect(screen.getByRole('button', { name: /Saya Setuju & Mulai/ })).toBeInTheDocument()
  })
})
