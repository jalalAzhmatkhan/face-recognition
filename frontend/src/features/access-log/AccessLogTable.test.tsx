import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AccessLogTable from './AccessLogTable'
import type { AccessEventPayload } from '../live-monitoring/types'

vi.mock('../user-management/api', () => ({
  getUser: vi.fn().mockResolvedValue({
    id: 'user-1',
    external_ref: 'ext-1',
    full_name: 'Budi Santoso',
    status: 'ACTIVE',
    created_at: '2026-08-30T00:00:00Z',
    updated_at: '2026-08-30T00:00:00Z',
  }),
}))

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const grantedEvent: AccessEventPayload = {
  id: 'evt-1',
  occurred_at: '2026-08-30T08:00:00Z',
  device_id: 'device-1',
  decision: 'GRANTED',
  matched_user_id: 'user-1',
  similarity: 0.95,
  liveness_score: 0.98,
  model_version: 'v1',
  latency_ms: 85,
  frame_media_id: null,
  door_command_issued: true,
}

afterEach(() => cleanup())

describe('AccessLogTable', () => {
  it('renders nothing (page handles the empty state) when there are no events', () => {
    const { container } = renderWithClient(
      <AccessLogTable events={[]} deviceNames={new Map()} isLoading={false} onSelectEvent={() => {}} />,
    )
    expect(container.querySelector('table')).not.toBeInTheDocument()
  })

  it('renders a skeleton table while loading', () => {
    const { container } = renderWithClient(
      <AccessLogTable events={[]} deviceNames={new Map()} isLoading onSelectEvent={() => {}} />,
    )
    expect(container.querySelector('table.access-log-table--skeleton')).toBeInTheDocument()
  })

  it('renders a row with device name, decision label, and mono metrics', async () => {
    renderWithClient(
      <AccessLogTable
        events={[grantedEvent]}
        deviceNames={new Map([['device-1', 'Pintu Lobby']])}
        isLoading={false}
        onSelectEvent={() => {}}
      />,
    )
    expect(screen.getByText('Pintu Lobby')).toBeInTheDocument()
    expect(screen.getByText(/Diizinkan/)).toBeInTheDocument()
    expect(screen.getByText('0.9500')).toBeInTheDocument()
    expect(await screen.findByText('Budi Santoso')).toBeInTheDocument()
  })

  it('calls onSelectEvent when a row is clicked', () => {
    const onSelectEvent = vi.fn()
    renderWithClient(
      <AccessLogTable
        events={[grantedEvent]}
        deviceNames={new Map([['device-1', 'Pintu Lobby']])}
        isLoading={false}
        onSelectEvent={onSelectEvent}
      />,
    )
    screen.getByRole('button', { name: /Pintu Lobby/ }).click()
    expect(onSelectEvent).toHaveBeenCalledWith(grantedEvent)
  })

  it('calls onSelectEvent on Enter keydown for keyboard accessibility', () => {
    const onSelectEvent = vi.fn()
    renderWithClient(
      <AccessLogTable
        events={[grantedEvent]}
        deviceNames={new Map()}
        isLoading={false}
        onSelectEvent={onSelectEvent}
      />,
    )
    const row = screen.getByRole('button', { name: /device-1/ })
    row.focus()
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(onSelectEvent).toHaveBeenCalledWith(grantedEvent)
  })
})
