import { describe, expect, it } from 'vitest'
import type { StaffRole } from '../../lib/authToken'
import { canAccessTrainingModels } from './roleGating'

const ROLES: (StaffRole | null)[] = ['ADMIN', 'OPERATOR', 'VIEWER', null]

describe('canAccessTrainingModels', () => {
  it('allows ADMIN and denies everyone else (screen-plan S-50/51/52 = access level A)', () => {
    expect(canAccessTrainingModels('ADMIN')).toBe(true)
    expect(canAccessTrainingModels('OPERATOR')).toBe(false)
    expect(canAccessTrainingModels('VIEWER')).toBe(false)
    expect(canAccessTrainingModels(null)).toBe(false)
  })

  it('never returns true for a non-ADMIN role, including ones the backend itself allows to read', () => {
    for (const role of ROLES) {
      if (role === 'ADMIN') continue
      expect(canAccessTrainingModels(role)).toBe(false)
    }
  })
})
