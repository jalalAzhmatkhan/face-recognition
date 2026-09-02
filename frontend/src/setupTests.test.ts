import { describe, expect, it, vi } from 'vitest'

/**
 * Guards for the shared test setup itself (`src/setupTests.ts`).
 *
 * These pin behaviour that a whole-suite flake depended on, so a future
 * "simplify the setup file" change cannot quietly reintroduce it.
 */
describe('test setup — unstubbed network requests', () => {
  it('rejects rather than reaching the network', async () => {
    // If this ever resolves again, an unstubbed call returns jsdom's 401,
    // `authFetch` treats that as an expired session, `refreshAccessToken()`
    // finds no refresh token and `clearTokens()` wipes the auth token out of
    // localStorage — from a fire-and-forget promise that can land in a
    // different test than the one that started it.
    await expect(fetch('/api/v1/anything')).rejects.toThrow(
      /Unstubbed network request/,
    )
  })

  it('lets a test stub fetch for itself', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
    await expect(fetch('/api/v1/anything')).resolves.toMatchObject({ status: 200 })
    vi.unstubAllGlobals()
  })

  it('restores the guard once a test unstubs its own fetch', async () => {
    await expect(fetch('/api/v1/anything')).rejects.toThrow(
      /Unstubbed network request/,
    )
  })
})

describe('test setup — storage isolation', () => {
  it('starts each test with empty storage', () => {
    expect(window.localStorage.length).toBe(0)
    window.localStorage.setItem('leaked', 'yes')
  })

  it('does not see what the previous test wrote', () => {
    // Cleared FORWARD (in beforeEach), not backward in an afterEach that
    // would run while the finished test's component tree is still mounted.
    expect(window.localStorage.getItem('leaked')).toBeNull()
  })
})
