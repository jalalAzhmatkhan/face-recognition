import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import OfflineDeviceBanner from './OfflineDeviceBanner'
import type { DeviceSummary } from './types'

afterEach(() => cleanup())

function device(overrides: Partial<DeviceSummary>): DeviceSummary {
  return {
    id: 'device-1',
    name: 'Pintu Lobby',
    door_group: 'lobby',
    status: 'ONLINE',
    last_heartbeat_at: '2026-08-30T08:00:00Z',
    credential_rotated_at: null,
    is_stale: false,
    ...overrides,
  }
}

describe('OfflineDeviceBanner', () => {
  it('renders nothing when all devices are online and fresh', () => {
    render(<OfflineDeviceBanner devices={[device({})]} />)
    expect(screen.queryByTestId('offline-banner')).not.toBeInTheDocument()
  })

  it('renders nothing for a DISABLED device (intentional, not an outage)', () => {
    render(<OfflineDeviceBanner devices={[device({ status: 'DISABLED' })]} />)
    expect(screen.queryByTestId('offline-banner')).not.toBeInTheDocument()
  })

  it('renders the fail-secure banner for an OFFLINE device', () => {
    render(<OfflineDeviceBanner devices={[device({ status: 'OFFLINE' })]} />)
    expect(screen.getByTestId('offline-banner')).toHaveTextContent('Pintu Lobby')
    expect(screen.getByTestId('offline-banner')).toHaveTextContent(/fail-secure/i)
  })

  it('renders the fail-secure banner for a stale (heartbeat-lapsed) device', () => {
    render(<OfflineDeviceBanner devices={[device({ is_stale: true })]} />)
    expect(screen.getByTestId('offline-banner')).toBeInTheDocument()
  })

  it('summarizes count when multiple devices are offline', () => {
    render(
      <OfflineDeviceBanner
        devices={[
          device({ id: 'a', status: 'OFFLINE' }),
          device({ id: 'b', status: 'OFFLINE' }),
        ]}
      />,
    )
    expect(screen.getByTestId('offline-banner')).toHaveTextContent('2 device')
  })
})
