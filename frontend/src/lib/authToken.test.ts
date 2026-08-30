import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearTokens,
  decodeJwtPayload,
  getAccessToken,
  getCurrentRole,
  getRefreshToken,
  isAccessTokenExpired,
  login,
  LoginError,
  refreshAccessToken,
  setTokens,
} from './authToken'

const ACCESS_TOKEN_KEY = 'frac_access_token'
const REFRESH_TOKEN_KEY = 'frac_refresh_token'

function base64url(input: string): string {
  const base64 = btoa(input)
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fakeJwt(payload: Record<string, unknown>): string {
  const header = base64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = base64url(JSON.stringify(payload))
  return `${header}.${body}.fake-signature`
}

afterEach(() => {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  window.localStorage.removeItem(REFRESH_TOKEN_KEY)
})

describe('getAccessToken', () => {
  it('reads the shared frac_access_token key', () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'abc123')
    expect(getAccessToken()).toBe('abc123')
  })

  it('returns null when nothing is stored', () => {
    expect(getAccessToken()).toBeNull()
  })
})

describe('decodeJwtPayload', () => {
  it('decodes a well-formed JWT payload', () => {
    const token = fakeJwt({ sub: 'staff-1', role: 'ADMIN', exp: 1234 })
    expect(decodeJwtPayload(token)).toEqual({ sub: 'staff-1', role: 'ADMIN', exp: 1234 })
  })

  it('returns null for a token with too few segments', () => {
    expect(decodeJwtPayload('not-a-jwt')).toBeNull()
  })

  it('returns null for a token whose payload segment is not valid base64/JSON', () => {
    expect(decodeJwtPayload('header.!!!not-base64!!!.sig')).toBeNull()
  })
})

describe('getCurrentRole', () => {
  it('returns the role claim for a known StaffRole', () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', role: 'OPERATOR' }))
    expect(getCurrentRole()).toBe('OPERATOR')
  })

  it('returns null when there is no stored token', () => {
    expect(getCurrentRole()).toBeNull()
  })

  it('returns null when the role claim is missing', () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1' }))
    expect(getCurrentRole()).toBeNull()
  })

  it('returns null when the role claim is not a recognized StaffRole', () => {
    window.localStorage.setItem(
      ACCESS_TOKEN_KEY,
      fakeJwt({ sub: 's1', role: 'SUPERUSER' }),
    )
    expect(getCurrentRole()).toBeNull()
  })

  it('returns null for a malformed stored token', () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'garbage')
    expect(getCurrentRole()).toBeNull()
  })
})

describe('setTokens / getRefreshToken / clearTokens', () => {
  it('stores both tokens under their respective keys', () => {
    setTokens({ access_token: 'acc-1', refresh_token: 'ref-1' })
    expect(getAccessToken()).toBe('acc-1')
    expect(getRefreshToken()).toBe('ref-1')
  })

  it('clearTokens wipes both keys', () => {
    setTokens({ access_token: 'acc-1', refresh_token: 'ref-1' })
    clearTokens()
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })
})

describe('isAccessTokenExpired', () => {
  it('treats a missing token as expired', () => {
    expect(isAccessTokenExpired()).toBe(true)
  })

  it('treats a token with no exp claim as expired', () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1' }))
    expect(isAccessTokenExpired()).toBe(true)
  })

  it('returns false for a token whose exp is in the future', () => {
    const exp = Math.floor(Date.now() / 1000) + 3600
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', exp }))
    expect(isAccessTokenExpired()).toBe(false)
  })

  it('returns true for a token whose exp is in the past', () => {
    const exp = Math.floor(Date.now() / 1000) - 60
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', exp }))
    expect(isAccessTokenExpired()).toBe(true)
  })

  it('honors a buffer, treating a token expiring soon as already expired', () => {
    const exp = Math.floor(Date.now() / 1000) + 30
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', exp }))
    expect(isAccessTokenExpired(60)).toBe(true)
    expect(isAccessTokenExpired(10)).toBe(false)
  })
})

describe('refreshAccessToken', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns null and clears tokens when there is no refresh token stored', async () => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'stale-access')
    const result = await refreshAccessToken()
    expect(result).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(getAccessToken()).toBeNull()
  })

  it('POSTs the refresh token and stores the new access token on success', async () => {
    setTokens({ access_token: 'old-access', refresh_token: 'ref-1' })
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ access_token: 'new-access', token_type: 'bearer', expires_in: 900 }),
        { status: 200 },
      ),
    )

    const result = await refreshAccessToken()

    expect(result).toBe('new-access')
    expect(getAccessToken()).toBe('new-access')
    // refresh token is NOT rotated by the backend, so it stays as-is
    expect(getRefreshToken()).toBe('ref-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/auth/refresh')
    expect(JSON.parse(init.body)).toEqual({ refresh_token: 'ref-1' })
  })

  it('clears both tokens and returns null on a 401', async () => {
    setTokens({ access_token: 'old-access', refresh_token: 'bad-ref' })
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: 'invalid' }), { status: 401 }))

    const result = await refreshAccessToken()

    expect(result).toBeNull()
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  it('clears tokens and returns null on a network error', async () => {
    setTokens({ access_token: 'old-access', refresh_token: 'ref-1' })
    fetchMock.mockRejectedValue(new Error('network down'))

    const result = await refreshAccessToken()

    expect(result).toBeNull()
    expect(getAccessToken()).toBeNull()
  })
})

describe('login', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts email/password and stores both tokens on success', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'acc-1',
          refresh_token: 'ref-1',
          token_type: 'bearer',
          expires_in: 900,
        }),
        { status: 200 },
      ),
    )

    await login({ email: 'staff@example.com', password: 'hunter2' })

    expect(getAccessToken()).toBe('acc-1')
    expect(getRefreshToken()).toBe('ref-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/auth/login')
    expect(JSON.parse(init.body)).toEqual({ email: 'staff@example.com', password: 'hunter2' })
  })

  it('throws a generic LoginError on 401 without leaking which field was wrong', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }))

    await expect(login({ email: 'x@example.com', password: 'wrong' })).rejects.toMatchObject({
      status: 401,
      message: 'Email atau password salah.',
    })
    expect(getAccessToken()).toBeNull()
  })

  it('throws a LoginError on other non-2xx statuses', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }))

    await expect(login({ email: 'x@example.com', password: 'y' })).rejects.toBeInstanceOf(
      LoginError,
    )
  })

  it('throws a LoginError when the network request itself fails', async () => {
    fetchMock.mockRejectedValue(new Error('offline'))

    await expect(login({ email: 'x@example.com', password: 'y' })).rejects.toBeInstanceOf(
      LoginError,
    )
  })
})
