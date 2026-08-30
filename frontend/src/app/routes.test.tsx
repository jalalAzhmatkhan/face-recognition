import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { routes } from './routes'

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
  it('renders the app shell with main navigation on /', () => {
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
    ['/monitoring', 'Monitoring'],
    ['/devices', 'Devices'],
    ['/models', 'Models & Training'],
  ])('renders placeholder screen at %s', (path, heading) => {
    renderAt(path)
    expect(
      screen.getByRole('heading', { level: 1, name: heading }),
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
