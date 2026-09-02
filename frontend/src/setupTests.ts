import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup, configure } from '@testing-library/react'

/**
 * Testing Library's default `findBy*`/`waitFor` deadline is 1000 ms, which
 * assumes the query is racing the app, not the machine. It isn't: vitest
 * runs this suite across ~15 forked jsdom workers, and under that
 * contention a step that takes 10 ms on its own was measured taking
 * 700-1500 ms. A 1000 ms budget then expires for reasons that have nothing
 * to do with the component, which is what made
 * `EnrollmentCapturePage.test.tsx` fail intermittently in full-suite runs
 * while always passing on its own.
 *
 * Raised to 3000 ms (with `testTimeout` lifted to match, see
 * vitest.config.ts) so an async wait fails only when the app really never
 * gets there. This buys headroom for a slow machine; it does NOT excuse
 * using an async query for something rendered synchronously — prefer
 * `getBy*` there, so the test has no deadline to blow at all.
 */
configure({ asyncUtilTimeout: 3000 })

beforeEach(() => {
  // Start every test from an empty Storage rather than trusting each suite
  // to undo its own writes afterwards. Cleaning up FORWARD (before) instead
  // of BACKWARD (after) matters: `afterEach` teardown runs while the tree
  // from the finished test is still mounted, so a suite that deleted its
  // auth token there could make a still-live component re-render into its
  // logged-out branch.
  window.localStorage.clear()
  window.sessionStorage.clear()
})

afterEach(() => {
  cleanup()
})

/**
 * Refuse real network I/O from tests.
 *
 * An unstubbed `fetch` in jsdom does not fail harmlessly — it comes back
 * `401`, and our `authFetch` helpers answer a 401 by calling
 * `refreshAccessToken()`, which finds no refresh token and runs
 * `clearTokens()`. So a single component test that forgot to stub one API
 * call silently DELETES the auth token out of localStorage. Because such a
 * request is typically fire-and-forget (a mount effect ending in
 * `.catch(() => {})`), it outlives the test that started it and does that to
 * whichever test happens to be running when it lands — the cause of a
 * long-standing intermittent failure in
 * `features/enrollment-capture/EnrollmentCapturePage.test.tsx`.
 *
 * Rejecting instead keeps that chain from ever starting (a rejected fetch
 * throws out of `authFetch` before the 401 branch) and turns "forgot to stub"
 * into a named, greppable error. Tests that need HTTP stub `fetch`
 * themselves, which replaces this.
 */
globalThis.fetch = (() =>
  Promise.reject(
    new Error(
      'Unstubbed network request in a test. Stub the API module (vi.spyOn) or ' +
        "global fetch (vi.stubGlobal('fetch', ...)) — see src/setupTests.ts.",
    ),
  )) as typeof globalThis.fetch

// jsdom does not implement matchMedia — needed by useTheme.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})
