import { afterEach, describe, expect, it } from 'vitest'
import { evaluateAuthGuard } from './authGuardLogic'

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

describe('evaluateAuthGuard', () => {
  it('denies when there is no access token and no refresh token', () => {
    expect(evaluateAuthGuard()).toBe('deny')
  })

  it('allows when the access token is present and not expired', () => {
    const exp = Math.floor(Date.now() / 1000) + 3600
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', role: 'VIEWER', exp }))
    expect(evaluateAuthGuard()).toBe('allow')
  })

  it('asks for a refresh when the access token is expired but a refresh token exists', () => {
    const exp = Math.floor(Date.now() / 1000) - 60
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', role: 'VIEWER', exp }))
    window.localStorage.setItem(REFRESH_TOKEN_KEY, 'some-refresh-token')
    expect(evaluateAuthGuard()).toBe('refresh')
  })

  it('denies when the access token is expired and there is no refresh token', () => {
    const exp = Math.floor(Date.now() / 1000) - 60
    window.localStorage.setItem(ACCESS_TOKEN_KEY, fakeJwt({ sub: 's1', role: 'VIEWER', exp }))
    expect(evaluateAuthGuard()).toBe('deny')
  })

  it('asks for a refresh when there is no access token but a refresh token exists', () => {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, 'some-refresh-token')
    expect(evaluateAuthGuard()).toBe('refresh')
  })
})
