import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ResetPasswordPage from './ResetPasswordPage'

const { resetPasswordMock, navigateMock } = vi.hoisted(() => ({
  resetPasswordMock: vi.fn(),
  navigateMock: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../lib/authToken', async () => {
  const actual = await vi.importActual<typeof import('../lib/authToken')>('../lib/authToken')
  return { ...actual, resetPassword: resetPasswordMock }
})

function renderPage(path = '/reset-password?token=token-id.secret') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ResetPasswordPage', () => {
  it('shows an invalid-link message when there is no token in the URL', () => {
    renderPage('/reset-password')
    expect(screen.getByRole('alert')).toHaveTextContent('Tautan reset password tidak valid')
    expect(screen.queryByLabelText('Password Baru')).not.toBeInTheDocument()
  })

  it('rejects submission when the passwords do not match', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Password Baru'), { target: { value: 'NewStrongPass!1' } })
    fireEvent.change(screen.getByLabelText('Konfirmasi Password Baru'), {
      target: { value: 'Different!2' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Konfirmasi password tidak cocok.')
    expect(resetPasswordMock).not.toHaveBeenCalled()
  })

  it('submits the token and new password, then shows success', async () => {
    resetPasswordMock.mockResolvedValue({ message: 'ok' })
    renderPage()

    fireEvent.change(screen.getByLabelText('Password Baru'), { target: { value: 'NewStrongPass!1' } })
    fireEvent.change(screen.getByLabelText('Konfirmasi Password Baru'), {
      target: { value: 'NewStrongPass!1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    await waitFor(() =>
      expect(resetPasswordMock).toHaveBeenCalledWith('token-id.secret', 'NewStrongPass!1'),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Password berhasil direset')
  })

  it('shows the backend error message when the token is invalid', async () => {
    const { PasswordResetError } = await import('../lib/authToken')
    resetPasswordMock.mockRejectedValue(
      new PasswordResetError(
        'Token reset password tidak valid, sudah digunakan, atau sudah kedaluwarsa.',
        400,
      ),
    )
    renderPage()

    fireEvent.change(screen.getByLabelText('Password Baru'), { target: { value: 'NewStrongPass!1' } })
    fireEvent.change(screen.getByLabelText('Konfirmasi Password Baru'), {
      target: { value: 'NewStrongPass!1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Token reset password tidak valid, sudah digunakan, atau sudah kedaluwarsa.',
    )
  })
})
