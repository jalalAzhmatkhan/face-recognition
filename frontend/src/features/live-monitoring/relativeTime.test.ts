import { describe, expect, it } from 'vitest'
import { formatEventTime, formatRelativeTime } from './relativeTime'

describe('formatRelativeTime', () => {
  const now = new Date('2026-08-30T12:00:00Z')

  it('returns "belum pernah" for null', () => {
    expect(formatRelativeTime(null, now)).toBe('belum pernah')
  })

  it('returns "belum pernah" for an unparseable date', () => {
    expect(formatRelativeTime('not-a-date', now)).toBe('belum pernah')
  })

  it('returns "baru saja" for under a second ago', () => {
    expect(formatRelativeTime('2026-08-30T11:59:59.900Z', now)).toBe('baru saja')
  })

  it('formats seconds', () => {
    expect(formatRelativeTime('2026-08-30T11:59:30Z', now)).toBe('30 detik lalu')
  })

  it('formats minutes', () => {
    expect(formatRelativeTime('2026-08-30T11:55:00Z', now)).toBe('5 menit lalu')
  })

  it('formats hours', () => {
    expect(formatRelativeTime('2026-08-30T09:00:00Z', now)).toBe('3 jam lalu')
  })

  it('formats days', () => {
    expect(formatRelativeTime('2026-08-27T12:00:00Z', now)).toBe('3 hari lalu')
  })
})

describe('formatEventTime', () => {
  it('renders a non-empty local time string for a valid ISO timestamp', () => {
    expect(formatEventTime('2026-08-30T12:00:00Z')).toBeTruthy()
  })
})
