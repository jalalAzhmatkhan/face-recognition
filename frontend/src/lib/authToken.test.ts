import { afterEach, describe, expect, it } from 'vitest'
import { decodeJwtPayload, getAccessToken, getCurrentRole } from './authToken'

const ACCESS_TOKEN_KEY = 'frac_access_token'

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
