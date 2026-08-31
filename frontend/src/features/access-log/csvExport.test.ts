import { describe, expect, it } from 'vitest'
import { buildAccessLogCsv } from './csvExport'
import type { AccessEventPayload } from '../live-monitoring/types'

const baseEvent: AccessEventPayload = {
  id: 'evt-1',
  occurred_at: '2026-08-30T08:00:00Z',
  device_id: 'device-1',
  decision: 'GRANTED',
  matched_user_id: 'user-1',
  similarity: 0.95,
  liveness_score: 0.98,
  model_version: 'adaface-v2',
  latency_ms: 85,
  frame_media_id: null,
  door_command_issued: true,
}

describe('buildAccessLogCsv', () => {
  it('includes a header row and resolves device/user names', () => {
    const csv = buildAccessLogCsv(
      [baseEvent],
      new Map([['device-1', 'Pintu Lobby']]),
      new Map([['user-1', 'Budi Santoso']]),
    )
    const lines = csv.split('\n')
    expect(lines[0]).toBe(
      'occurred_at,device,decision,matched_user,similarity,liveness_score,model_version,latency_ms,door_command_issued',
    )
    expect(lines[1]).toBe(
      '2026-08-30T08:00:00Z,Pintu Lobby,GRANTED,Budi Santoso,0.95,0.98,adaface-v2,85,true',
    )
  })

  it('falls back to raw ids when device/user names are unresolved', () => {
    const csv = buildAccessLogCsv([baseEvent], new Map(), new Map())
    const lines = csv.split('\n')
    expect(lines[1]).toContain('device-1')
    expect(lines[1]).toContain('user-1')
  })

  it('leaves matched_user blank when there is no matched user', () => {
    const csv = buildAccessLogCsv(
      [{ ...baseEvent, matched_user_id: null }],
      new Map(),
      new Map(),
    )
    const columns = csv.split('\n')[1].split(',')
    expect(columns[3]).toBe('')
  })

  it('renders null similarity/liveness/model_version/latency as empty fields', () => {
    const csv = buildAccessLogCsv(
      [
        {
          ...baseEvent,
          similarity: null,
          liveness_score: null,
          model_version: null,
          latency_ms: null,
        },
      ],
      new Map(),
      new Map(),
    )
    const columns = csv.split('\n')[1].split(',')
    expect(columns).toEqual([
      '2026-08-30T08:00:00Z',
      'device-1',
      'GRANTED',
      'user-1',
      '',
      '',
      '',
      '',
      'true',
    ])
  })

  it('never includes frame_media_id (metadata-only export)', () => {
    const csv = buildAccessLogCsv(
      [{ ...baseEvent, frame_media_id: 'media-object-id-should-not-leak' }],
      new Map(),
      new Map(),
    )
    expect(csv).not.toContain('media-object-id-should-not-leak')
    expect(csv).not.toContain('frame_media_id')
  })

  it('quotes and escapes device/user names containing commas or quotes', () => {
    const csv = buildAccessLogCsv(
      [baseEvent],
      new Map([['device-1', 'Pintu, Lobby "Utama"']]),
      new Map(),
    )
    const dataLine = csv.split('\n')[1]
    expect(dataLine).toContain('"Pintu, Lobby ""Utama"""')
  })

  it('returns just the header row for an empty event list', () => {
    const csv = buildAccessLogCsv([], new Map(), new Map())
    expect(csv.split('\n')).toHaveLength(1)
  })
})
