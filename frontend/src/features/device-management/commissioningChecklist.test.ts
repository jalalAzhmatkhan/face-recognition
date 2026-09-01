import { describe, expect, it } from 'vitest'
import {
  buildDefaultChecklist,
  computeOverallStatus,
  reclassifyChecklist,
} from './commissioningChecklist'

describe('buildDefaultChecklist', () => {
  it('builds all 13 catalog items with the right applicability per class', () => {
    const attendance = buildDefaultChecklist('attendance')
    expect(attendance.checks).toHaveLength(13)
    expect(attendance.queue_zone).not.toBeNull()
    // Every item applies to attendance (mounting/lighting/camera_settings/
    // occlusion_policy are "keduanya", queue_zone is "attendance saja").
    expect(attendance.checks.every((c) => c.status === null)).toBe(true)

    const doorEntry = buildDefaultChecklist('door_entry')
    expect(doorEntry.checks).toHaveLength(13)
    expect(doorEntry.queue_zone).toBeNull()
    const queueItems = doorEntry.checks.filter((c) => c.category === 'queue_zone')
    expect(queueItems).toHaveLength(3)
    expect(queueItems.every((c) => c.status === 'na')).toBe(true)
    const nonQueueItems = doorEntry.checks.filter((c) => c.category !== 'queue_zone')
    expect(nonQueueItems.every((c) => c.status === null)).toBe(true)
  })

  it('sets device-class-specific expected_range for mount.camera_height_m', () => {
    const attendance = buildDefaultChecklist('attendance')
    const doorEntry = buildDefaultChecklist('door_entry')
    const heightAttendance = attendance.checks.find((c) => c.id === 'mount.camera_height_m')
    const heightDoorEntry = doorEntry.checks.find((c) => c.id === 'mount.camera_height_m')
    expect(heightAttendance?.expected_range).toEqual({ min: 1.5, max: 1.6 })
    expect(heightDoorEntry?.expected_range).toEqual({ min: 1.4, max: 1.7 })
  })
})

describe('reclassifyChecklist', () => {
  it('preserves measured_value/notes but resets status appropriately when class changes', () => {
    const checklist = buildDefaultChecklist('door_entry')
    const withMeasurement = {
      ...checklist,
      checks: checklist.checks.map((c) =>
        c.id === 'mount.pitch_degrees' ? { ...c, measured_value: 2, status: 'pass' as const } : c,
      ),
    }

    const reclassified = reclassifyChecklist(withMeasurement, 'attendance')
    const pitch = reclassified.checks.find((c) => c.id === 'mount.pitch_degrees')
    expect(pitch?.measured_value).toBe(2)
    expect(pitch?.status).toBe('pass')

    // queue_zone items were 'na' under door_entry, become uncheck (null)
    // under attendance since they are now applicable.
    const queueItem = reclassified.checks.find((c) => c.id === 'queue_zone.stop_point_defined')
    expect(queueItem?.status).toBeNull()
    expect(reclassified.queue_zone).not.toBeNull()
  })

  it('drops queue_zone back to na/null when switching away from attendance', () => {
    const checklist = buildDefaultChecklist('attendance')
    const reclassified = reclassifyChecklist(checklist, 'door_entry')
    expect(reclassified.queue_zone).toBeNull()
    const queueItem = reclassified.checks.find((c) => c.id === 'queue_zone.stop_point_defined')
    expect(queueItem?.status).toBe('na')
  })
})

describe('computeOverallStatus', () => {
  it('is "pending" while any required applicable item is unchecked', () => {
    const checklist = buildDefaultChecklist('door_entry')
    expect(computeOverallStatus(checklist.checks, 'door_entry')).toBe('pending')
  })

  it('is "failed" if any required applicable item failed, even if others pass', () => {
    const checklist = buildDefaultChecklist('door_entry')
    const checks = checklist.checks.map((c, i) => ({
      ...c,
      status: c.status === 'na' ? c.status : i === 0 ? ('fail' as const) : ('pass' as const),
    }))
    expect(computeOverallStatus(checks, 'door_entry')).toBe('failed')
  })

  it('is "passed" once every required applicable item is pass/fail-free and checked', () => {
    const checklist = buildDefaultChecklist('door_entry')
    const checks = checklist.checks.map((c) => (c.status === 'na' ? c : { ...c, status: 'pass' as const }))
    expect(computeOverallStatus(checks, 'door_entry')).toBe('passed')
  })

  it('ignores non-required items entirely (helmet signage can stay unchecked)', () => {
    const checklist = buildDefaultChecklist('door_entry')
    const checks = checklist.checks.map((c) => {
      if (c.status === 'na') return c
      if (c.id === 'occlusion_policy.helmet_removal_signage') return c // stays null, not required
      return { ...c, status: 'pass' as const }
    })
    expect(computeOverallStatus(checks, 'door_entry')).toBe('passed')
  })

  it('excludes inapplicable required items (queue_zone) for a door_entry device', () => {
    const checklist = buildDefaultChecklist('door_entry')
    const checks = checklist.checks.map((c) => (c.status === 'na' ? c : { ...c, status: 'pass' as const }))
    // queue_zone items remain 'na' (inapplicable) and must not force pending.
    expect(computeOverallStatus(checks, 'door_entry')).toBe('passed')
  })
})
