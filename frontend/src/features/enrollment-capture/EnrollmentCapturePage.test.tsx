import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import EnrollmentCapturePage from './EnrollmentCapturePage'

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
