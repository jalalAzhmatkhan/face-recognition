import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BootstrapAdminError, bootstrapAdmin, getAccessToken, getSetupStatus } from './authToken'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  fetchMock.mockReset()
  window.localStorage.clear()
})

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('getSetupStatus', () => {
  it('returns the parsed body on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { needs_setup: true }))
    await expect(getSetupStatus()).resolves.toEqual({ needs_setup: true })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/setup-status'),
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
  })

  it('throws on a non-ok response', async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, {}))
    await expect(getSetupStatus()).rejects.toThrow()
  })
})

describe('bootstrapAdmin', () => {
  it('stores tokens and resolves on success', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { access_token: 'access-1', refresh_token: 'refresh-1' }),
    )
    await bootstrapAdmin({ email: 'admin@example.com', password: 'S0meStrongPass!' })
    expect(getAccessToken()).toBe('access-1')
  })

  it('throws a BootstrapAdminError with a specific message on 409', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, { detail: 'An ADMIN account already exists; bootstrap is only available once.' }),
    )
    await expect(
      bootstrapAdmin({ email: 'admin@example.com', password: 'S0meStrongPass!' }),
    ).rejects.toMatchObject({
      status: 409,
      message: 'An ADMIN account already exists; bootstrap is only available once.',
    })
  })

  it('throws a BootstrapAdminError on 422 without a detail body', async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, {}))
    const error = await bootstrapAdmin({ email: 'x', password: 'short' }).catch((err) => err)
    expect(error).toBeInstanceOf(BootstrapAdminError)
    expect(error.status).toBe(422)
  })

  it('throws a BootstrapAdminError when the network request itself fails', async () => {
    fetchMock.mockRejectedValue(new TypeError('network down'))
    await expect(
      bootstrapAdmin({ email: 'admin@example.com', password: 'S0meStrongPass!' }),
    ).rejects.toBeInstanceOf(BootstrapAdminError)
  })
})
