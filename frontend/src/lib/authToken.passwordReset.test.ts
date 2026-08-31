import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PasswordResetError, forgotPassword, resetPassword } from './authToken'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('forgotPassword', () => {
  it('resolves with the generic message on success', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { message: 'Jika email terdaftar, tautan reset password telah dikirim.' }),
    )
    await expect(forgotPassword('admin@example.com')).resolves.toEqual({
      message: 'Jika email terdaftar, tautan reset password telah dikirim.',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/forgot-password'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'admin@example.com' }),
      }),
    )
  })

  it('throws a PasswordResetError when the request itself fails', async () => {
    fetchMock.mockRejectedValue(new TypeError('network down'))
    await expect(forgotPassword('admin@example.com')).rejects.toBeInstanceOf(PasswordResetError)
  })
})

describe('resetPassword', () => {
  it('resolves on success', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { message: 'Password berhasil direset. Silakan login dengan password baru.' }),
    )
    await expect(resetPassword('token-id.secret', 'NewStrongPass!1')).resolves.toEqual({
      message: 'Password berhasil direset. Silakan login dengan password baru.',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/reset-password'),
      expect.objectContaining({
        body: JSON.stringify({ token: 'token-id.secret', new_password: 'NewStrongPass!1' }),
      }),
    )
  })

  it('throws a PasswordResetError with the backend detail on 400', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, {
        detail: 'Token reset password tidak valid, sudah digunakan, atau sudah kedaluwarsa.',
      }),
    )
    await expect(resetPassword('bad.token', 'NewStrongPass!1')).rejects.toMatchObject({
      status: 400,
      message: 'Token reset password tidak valid, sudah digunakan, atau sudah kedaluwarsa.',
    })
  })
})
