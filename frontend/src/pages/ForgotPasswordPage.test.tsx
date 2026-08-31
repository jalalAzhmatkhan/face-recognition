import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ForgotPasswordPage from './ForgotPasswordPage'

const { forgotPasswordMock } = vi.hoisted(() => ({ forgotPasswordMock: vi.fn() }))

vi.mock('../lib/authToken', async () => {
  const actual = await vi.importActual<typeof import('../lib/authToken')>('../lib/authToken')
  return { ...actual, forgotPassword: forgotPasswordMock }
})

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ForgotPasswordPage', () => {
  it('shows the generic success message after submitting a known-looking email', async () => {
    forgotPasswordMock.mockResolvedValue({ message: 'ok' })
    renderPage()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'admin@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Kirim Tautan Reset' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Jika email terdaftar, tautan reset password telah dikirim.',
    )
    expect(forgotPasswordMock).toHaveBeenCalledWith('admin@example.com')
  })

  it('shows the SAME generic success message for an email that does not exist', async () => {
    forgotPasswordMock.mockResolvedValue({ message: 'ok' })
    renderPage()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ghost@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Kirim Tautan Reset' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Jika email terdaftar, tautan reset password telah dikirim.',
    )
  })

  it('shows an error message when the request itself fails', async () => {
    const { PasswordResetError } = await import('../lib/authToken')
    forgotPasswordMock.mockRejectedValue(
      new PasswordResetError('Tidak dapat terhubung ke server. Coba lagi.', 0),
    )
    renderPage()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'admin@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Kirim Tautan Reset' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Tidak dapat terhubung ke server. Coba lagi.'),
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
