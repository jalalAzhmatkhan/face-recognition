import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import SpoofBanner from './SpoofBanner'

afterEach(() => cleanup())

describe('SpoofBanner', () => {
  it('renders nothing when there are no unreviewed spoof events', () => {
    render(<SpoofBanner unreviewedCount={0} />)
    expect(screen.queryByTestId('spoof-banner')).not.toBeInTheDocument()
  })

  it('renders an alert with the unreviewed count', () => {
    render(<SpoofBanner unreviewedCount={2} />)
    const banner = screen.getByTestId('spoof-banner')
    expect(banner).toBeInTheDocument()
    expect(banner).toHaveTextContent('2 event dicurigai spoof belum ditinjau')
  })
})
