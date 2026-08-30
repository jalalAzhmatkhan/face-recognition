import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AccessEventFeed from './AccessEventFeed'
import type { AccessEventPayload } from './types'

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
  door_command_issued: true,
}

const spoofEvent: AccessEventPayload = {
  ...grantedEvent,
  id: 'evt-2',
  decision: 'SPOOF_SUSPECTED',
  matched_user_id: null,
}

afterEach(() => cleanup())

describe('AccessEventFeed', () => {
  it('renders the empty state when there are no events and nothing is loading', () => {
    renderWithClient(
      <AccessEventFeed
        events={[]}
        deviceNames={new Map()}
        isLoading={false}
        reviewedSpoofIds={new Set()}
        onMarkReviewed={() => {}}
        newIds={new Set()}
      />,
    )
    expect(screen.getByText('Belum ada aktivitas')).toBeInTheDocument()
  })

  it('renders a skeleton while loading with no events yet', () => {
    renderWithClient(
      <AccessEventFeed
        events={[]}
        deviceNames={new Map()}
        isLoading
        reviewedSpoofIds={new Set()}
        onMarkReviewed={() => {}}
        newIds={new Set()}
      />,
    )
    expect(screen.queryByText('Belum ada aktivitas')).not.toBeInTheDocument()
  })

  it('renders one event with device name, decision label, and metrics', async () => {
    renderWithClient(
      <AccessEventFeed
        events={[grantedEvent]}
        deviceNames={new Map([['device-1', 'Pintu Lobby']])}
        isLoading={false}
        reviewedSpoofIds={new Set()}
        onMarkReviewed={() => {}}
        newIds={new Set()}
      />,
    )
    expect(screen.getByText('Pintu Lobby')).toBeInTheDocument()
    expect(screen.getByText(/Diizinkan/)).toBeInTheDocument()
    expect(screen.getByText(/0.95/)).toBeInTheDocument()
    expect(await screen.findByText('Budi Santoso')).toBeInTheDocument()
  })

  it('falls back to the device id and "—" for user when unresolved', () => {
    renderWithClient(
      <AccessEventFeed
        events={[{ ...grantedEvent, matched_user_id: null }]}
        deviceNames={new Map()}
        isLoading={false}
        reviewedSpoofIds={new Set()}
        onMarkReviewed={() => {}}
        newIds={new Set()}
      />,
    )
    expect(screen.getByText('device-1')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows the non-persistent "tandai ditinjau" action on a spoof-suspected event', () => {
    const onMarkReviewed = vi.fn()
    renderWithClient(
      <AccessEventFeed
        events={[spoofEvent]}
        deviceNames={new Map()}
        isLoading={false}
        reviewedSpoofIds={new Set()}
        onMarkReviewed={onMarkReviewed}
        newIds={new Set()}
      />,
    )
    expect(screen.getByText(/Dicurigai spoof/)).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Tandai ditinjau' })
    button.click()
    expect(onMarkReviewed).toHaveBeenCalledWith('evt-2')
    expect(screen.getByText(/belum tersimpan permanen/)).toBeInTheDocument()
  })

  it('shows the reviewed note instead of the button once marked reviewed', () => {
    renderWithClient(
      <AccessEventFeed
        events={[spoofEvent]}
        deviceNames={new Map()}
        isLoading={false}
        reviewedSpoofIds={new Set(['evt-2'])}
        onMarkReviewed={() => {}}
        newIds={new Set()}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Tandai ditinjau' })).not.toBeInTheDocument()
    expect(screen.getByText('Ditandai ditinjau untuk sesi ini saja')).toBeInTheDocument()
  })
})
