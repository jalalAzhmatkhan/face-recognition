import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import EdgeCaseFunnelPanel from './EdgeCaseFunnelPanel'
import type { AccessEventSample } from './types'

afterEach(() => cleanup())

function event(overrides: Partial<AccessEventSample> = {}): AccessEventSample {
  return {
    id: 'evt-1',
    decision: 'DENIED',
    reject_stage: null,
    condition_flags: null,
    device_class: null,
    ...overrides,
  }
}

describe('EdgeCaseFunnelPanel', () => {
  it('shows a skeleton while loading', () => {
    const { container } = render(<EdgeCaseFunnelPanel events={[]} isLoading />)
    expect(container.querySelector('.dashboard-panel--skeleton')).toBeInTheDocument()
  })

  it('shows an empty hint when there is no data', () => {
    render(<EdgeCaseFunnelPanel events={[]} isLoading={false} />)
    expect(screen.getByText('Belum ada access event untuk dianalisis.')).toBeInTheDocument()
  })

  it('renders reject-stage, condition-flag, and device-class breakdown sections from real events', () => {
    render(
      <EdgeCaseFunnelPanel
        events={[
          event({ decision: 'GRANTED' }),
          event({ decision: 'DENIED', reject_stage: 'liveness', condition_flags: { masked: true } }),
          event({ decision: 'DENIED', reject_stage: 'quality_gate', device_class: 'attendance' }),
        ]}
        isLoading={false}
      />,
    )
    expect(screen.getByText('Per Reject Stage')).toBeInTheDocument()
    expect(screen.getByText('Per Flag Kondisi')).toBeInTheDocument()
    expect(screen.getByText('Per Device Class')).toBeInTheDocument()
    expect(screen.getByText('Liveness gagal')).toBeInTheDocument()
    expect(screen.getByText('Bermasker')).toBeInTheDocument()
    expect(screen.getByText('Absensi')).toBeInTheDocument()
    expect(screen.getByText(/3 access event terbaru/)).toBeInTheDocument()
  })
})
