import { describe, expect, it } from 'vitest'
import type { StaffRole } from '../../lib/authToken'
import {
  canCreateDevice,
  canDisableDevice,
  canEditDevice,
  canReadDevices,
  canRotateDeviceCredential,
} from './roleGating'

const ROLES: (StaffRole | null)[] = ['ADMIN', 'OPERATOR', 'VIEWER', null]

describe('canReadDevices', () => {
  it('allows ADMIN and OPERATOR, denies VIEWER and unauthenticated', () => {
    expect(canReadDevices('ADMIN')).toBe(true)
    expect(canReadDevices('OPERATOR')).toBe(true)
    expect(canReadDevices('VIEWER')).toBe(false)
    expect(canReadDevices(null)).toBe(false)
  })
})

describe('write-role gates for device management (ADMIN only, unlike most other screens)', () => {
  const gates = [canCreateDevice, canEditDevice, canRotateDeviceCredential, canDisableDevice]

  it('allows only ADMIN for every write action', () => {
    for (const gate of gates) {
      expect(gate('ADMIN')).toBe(true)
      expect(gate('OPERATOR')).toBe(false)
      expect(gate('VIEWER')).toBe(false)
      expect(gate(null)).toBe(false)
    }
  })

  it('never returns true for an unrecognized role', () => {
    for (const gate of gates) {
      for (const role of ROLES) {
        if (role === 'ADMIN') continue
        expect(gate(role)).toBe(false)
      }
    }
  })
})
