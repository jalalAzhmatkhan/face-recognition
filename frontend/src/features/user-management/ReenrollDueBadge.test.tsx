import { describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach } from 'vitest'
import ReenrollDueBadge from './ReenrollDueBadge'
import { isReenrollDue } from './types'

afterEach(cleanup)

describe('isReenrollDue (EC-FE-03)', () => {
  it('is true only when reenroll_due is exactly true', () => {
    expect(isReenrollDue({ reenroll_due: true })).toBe(true)
    expect(isReenrollDue({ reenroll_due: false })).toBe(false)
    // The backend gap case: `UserResponse` today never sends this field at
    // all (see the GAP comment in `./types`) — must not be treated as due.
    expect(isReenrollDue({})).toBe(false)
    expect(isReenrollDue({ reenroll_due: undefined })).toBe(false)
  })
})

describe('ReenrollDueBadge (EC-FE-03)', () => {
  it('renders the badge with the reason as a tooltip when reenroll_due is true', () => {
    render(
      <ReenrollDueBadge
        user={{ reenroll_due: true, reenroll_due_reason: 'enrollment_older_than_24_months' }}
      />,
    )
    const badge = screen.getByText('Perlu Re-enroll')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute('title', 'enrollment_older_than_24_months')
  })

  it('renders nothing when reenroll_due is false', () => {
    render(<ReenrollDueBadge user={{ reenroll_due: false }} />)
    expect(screen.queryByText('Perlu Re-enroll')).not.toBeInTheDocument()
  })

  it('renders nothing when reenroll_due is absent (today\'s real backend response shape)', () => {
    render(<ReenrollDueBadge user={{}} />)
    expect(screen.queryByText('Perlu Re-enroll')).not.toBeInTheDocument()
  })
})
