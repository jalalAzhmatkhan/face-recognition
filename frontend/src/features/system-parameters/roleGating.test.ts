import { describe, expect, it } from 'vitest'
import type { StaffRole } from '../../lib/authToken'
import { canAccessSystemParameters } from './roleGating'

const ROLES: (StaffRole | null)[] = ['ADMIN', 'OPERATOR', 'VIEWER', null]

describe('canAccessSystemParameters', () => {
  it('allows ADMIN and denies everyone else', () => {
    expect(canAccessSystemParameters('ADMIN')).toBe(true)
    expect(canAccessSystemParameters('OPERATOR')).toBe(false)
    expect(canAccessSystemParameters('VIEWER')).toBe(false)
    expect(canAccessSystemParameters(null)).toBe(false)
  })

  it('never returns true for a non-ADMIN role, including ones the backend itself allows to read', () => {
    for (const role of ROLES) {
      if (role === 'ADMIN') continue
      expect(canAccessSystemParameters(role)).toBe(false)
    }
  })
})
