import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { routes } from './routes'

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

function setValidToken() {
  const oneHourFromNow = Math.floor(Date.now() / 1000) + 3600
  window.localStorage.setItem(
    ACCESS_TOKEN_KEY,
    fakeJwt({ sub: 'staff-1', role: 'ADMIN', exp: oneHourFromNow }),
  )
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const queryClient = new QueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('routing shell', () => {
  beforeEach(() => {
    setValidToken()
  })

  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  })

  it('renders the app shell with main navigation on / when logged in', () => {
    renderAt('/')
    expect(
      screen.getByRole('navigation', { name: /navigasi utama/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Users' })).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Dashboard' }),
    ).toBeInTheDocument()
  })

  it.each([
    ['/users', 'Users'],
    ['/enrollments', 'Enrollment'],
    ['/devices', 'Devices'],
    ['/models', 'Models & Training'],
  ])('renders placeholder screen at %s', (path, heading) => {
    renderAt(path)
    expect(
      screen.getByRole('heading', { level: 1, name: heading }),
    ).toBeInTheDocument()
  })

  // FE-06: /monitoring has no screen of its own (S-42 Access Log isn't
  // built yet) — it redirects to S-40's official path, /monitoring/live.
  it('redirects /monitoring to /monitoring/live (S-40)', () => {
    renderAt('/monitoring')
    expect(
      screen.getByRole('heading', { level: 1, name: 'Live Monitoring' }),
    ).toBeInTheDocument()
  })

  it('renders the live monitoring screen at /monitoring/live', () => {
    renderAt('/monitoring/live')
    expect(
      screen.getByRole('heading', { level: 1, name: 'Live Monitoring' }),
    ).toBeInTheDocument()
  })

  it('renders login outside the app shell', () => {
    renderAt('/login')
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 1, name: /frac console/i }),
    ).toBeInTheDocument()
  })

  it('renders 404 page for unknown routes', () => {
    renderAt('/does-not-exist')
    expect(
      screen.getByRole('heading', { name: /tidak ditemukan/i }),
    ).toBeInTheDocument()
  })
})

describe('FE-02 auth guard', () => {
  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
  })

  it('redirects to /login when there is no token at all', () => {
    renderAt('/')
    expect(
      screen.getByRole('heading', { level: 1, name: /frac console/i }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('redirects a deep shell route to /login when logged out', () => {
    renderAt('/users')
    expect(
      screen.getByRole('heading', { level: 1, name: /frac console/i }),
    ).toBeInTheDocument()
  })
})
