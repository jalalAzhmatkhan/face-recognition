import { describe, expect, it } from 'vitest'
import type { StaffRole } from '../../lib/authToken'
import {
  canChangeUserStatus,
  canCreateUser,
  canEditUser,
  canOffboardUser,
  canStartEnrollment,
  canViewIdentitySimilarityFlags,
} from './roleGating'

const ROLES: (StaffRole | null)[] = ['ADMIN', 'OPERATOR', 'VIEWER', null]

describe('write-role gates for user management', () => {
  const gates = [
    canCreateUser,
    canEditUser,
    canChangeUserStatus,
    canOffboardUser,
    canStartEnrollment,
  ]

  it('allows ADMIN and OPERATOR, denies VIEWER and unauthenticated, for every write action', () => {
    for (const gate of gates) {
      expect(gate('ADMIN')).toBe(true)
      expect(gate('OPERATOR')).toBe(true)
      expect(gate('VIEWER')).toBe(false)
      expect(gate(null)).toBe(false)
    }
  })

  it('never returns true for an unrecognized role', () => {
    for (const gate of gates) {
      for (const role of ROLES) {
        if (role === 'ADMIN' || role === 'OPERATOR') continue
        expect(gate(role)).toBe(false)
      }
    }
  })
})

describe('canViewIdentitySimilarityFlags (EC-FE-03, ADMIN-only)', () => {
  it('allows only ADMIN', () => {
    expect(canViewIdentitySimilarityFlags('ADMIN')).toBe(true)
    expect(canViewIdentitySimilarityFlags('OPERATOR')).toBe(false)
    expect(canViewIdentitySimilarityFlags('VIEWER')).toBe(false)
    expect(canViewIdentitySimilarityFlags(null)).toBe(false)
  })
})
