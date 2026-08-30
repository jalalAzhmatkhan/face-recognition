import { describe, expect, it } from 'vitest'
import {
  canCancel,
  canCreateEnrollment,
  canGrantConsent,
  canRecapture,
  canRevoke,
  visibleActions,
} from './roleGating'
import { ENROLLMENT_STATES } from './types'
import type { EnrollmentState, StaffRole } from './types'

const ROLES: (StaffRole | null)[] = ['ADMIN', 'OPERATOR', 'VIEWER', null]

describe('canCreateEnrollment', () => {
  it('allows ADMIN and OPERATOR, not VIEWER or unauthenticated', () => {
    expect(canCreateEnrollment('ADMIN')).toBe(true)
    expect(canCreateEnrollment('OPERATOR')).toBe(true)
    expect(canCreateEnrollment('VIEWER')).toBe(false)
    expect(canCreateEnrollment(null)).toBe(false)
  })
})

describe('canGrantConsent', () => {
  it('is true only for CREATED + ADMIN/OPERATOR', () => {
    expect(canGrantConsent('CREATED', 'ADMIN')).toBe(true)
    expect(canGrantConsent('CREATED', 'OPERATOR')).toBe(true)
    expect(canGrantConsent('CREATED', 'VIEWER')).toBe(false)
    expect(canGrantConsent('CONSENTED', 'ADMIN')).toBe(false)
  })
})

describe('canRecapture', () => {
  it('is true for CONSENTED or REJECTED_QUALITY + ADMIN/OPERATOR', () => {
    expect(canRecapture('CONSENTED', 'ADMIN')).toBe(true)
    expect(canRecapture('REJECTED_QUALITY', 'OPERATOR')).toBe(true)
    expect(canRecapture('CONSENTED', 'VIEWER')).toBe(false)
    expect(canRecapture('CAPTURING', 'ADMIN')).toBe(false)
    expect(canRecapture('CREATED', 'ADMIN')).toBe(false)
  })
})

describe('canCancel', () => {
  it('is true for any non-terminal state except ENROLLED + ADMIN/OPERATOR (ENROLLED has no /cancel edge)', () => {
    for (const state of ENROLLMENT_STATES) {
      const terminal = state === 'CANCELLED' || state === 'REVOKED' || state === 'ENROLLED'
      expect(canCancel(state, 'ADMIN')).toBe(!terminal)
      expect(canCancel(state, 'OPERATOR')).toBe(!terminal)
    }
  })

  it('is always false for VIEWER regardless of state', () => {
    for (const state of ENROLLMENT_STATES) {
      expect(canCancel(state, 'VIEWER')).toBe(false)
    }
  })
})

describe('canRevoke', () => {
  it('is true only for ENROLLED + ADMIN (never OPERATOR, even though OPERATOR can write elsewhere)', () => {
    expect(canRevoke('ENROLLED', 'ADMIN')).toBe(true)
    expect(canRevoke('ENROLLED', 'OPERATOR')).toBe(false)
    expect(canRevoke('ENROLLED', 'VIEWER')).toBe(false)
    expect(canRevoke('ENROLLED', null)).toBe(false)
  })

  it('is false for every other state even for ADMIN', () => {
    for (const state of ENROLLMENT_STATES) {
      if (state === 'ENROLLED') continue
      expect(canRevoke(state, 'ADMIN')).toBe(false)
    }
  })
})

describe('visibleActions', () => {
  it('is always empty for VIEWER, across every state', () => {
    for (const state of ENROLLMENT_STATES) {
      expect(visibleActions(state, 'VIEWER')).toEqual([])
    }
  })

  it('is always empty when unauthenticated', () => {
    for (const state of ENROLLMENT_STATES) {
      expect(visibleActions(state, null)).toEqual([])
    }
  })

  it('exposes "consent" and "cancel" for CREATED + OPERATOR (CREATED is non-terminal)', () => {
    expect(visibleActions('CREATED', 'OPERATOR')).toEqual(['consent', 'cancel'])
  })

  it('exposes "recapture" and "cancel" for CONSENTED + ADMIN', () => {
    expect(visibleActions('CONSENTED', 'ADMIN')).toEqual(['recapture', 'cancel'])
  })

  it('exposes "recapture" and "cancel" for REJECTED_QUALITY + OPERATOR', () => {
    expect(visibleActions('REJECTED_QUALITY', 'OPERATOR')).toEqual(['recapture', 'cancel'])
  })

  it('exposes only "revoke" for ENROLLED + ADMIN (ENROLLED has no /cancel edge, only DELETE/revoke)', () => {
    expect(visibleActions('ENROLLED', 'ADMIN')).toEqual(['revoke'])
  })

  it('exposes nothing for ENROLLED + OPERATOR (revoke is ADMIN-only, cancel is not a legal edge from ENROLLED)', () => {
    expect(visibleActions('ENROLLED', 'OPERATOR')).toEqual([])
  })

  it('exposes only "cancel" for an in-flight state like QC_RUNNING + ADMIN', () => {
    expect(visibleActions('QC_RUNNING', 'ADMIN')).toEqual(['cancel'])
  })

  it('exposes nothing for terminal states regardless of role', () => {
    const terminal: EnrollmentState[] = ['CANCELLED', 'REVOKED']
    for (const state of terminal) {
      for (const role of ROLES) {
        expect(visibleActions(state, role)).toEqual([])
      }
    }
  })
})
