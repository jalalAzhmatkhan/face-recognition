import { describe, expect, it } from 'vitest'
import { parseSseBuffer } from './sseParser'

const sampleEvent = {
  id: 'evt-1',
  occurred_at: '2026-08-30T08:00:00Z',
  device_id: 'device-1',
  decision: 'GRANTED',
  matched_user_id: 'user-1',
  similarity: 0.92,
  liveness_score: 0.99,
  model_version: 'v1',
  latency_ms: 120,
  door_command_issued: true,
}

describe('parseSseBuffer', () => {
  it('parses a single complete event', () => {
    const chunk = `data: ${JSON.stringify(sampleEvent)}\n\n`
    const { events, remainder } = parseSseBuffer(chunk)
    expect(events).toEqual([sampleEvent])
    expect(remainder).toBe('')
  })

  it('parses multiple events in one buffer', () => {
    const second = { ...sampleEvent, id: 'evt-2', decision: 'DENIED' }
    const chunk = `data: ${JSON.stringify(sampleEvent)}\n\ndata: ${JSON.stringify(second)}\n\n`
    const { events } = parseSseBuffer(chunk)
    expect(events.map((e) => e.id)).toEqual(['evt-1', 'evt-2'])
  })

  it('ignores keep-alive comment lines', () => {
    const { events, remainder } = parseSseBuffer(': keep-alive\n\n')
    expect(events).toEqual([])
    expect(remainder).toBe('')
  })

  it('skips malformed JSON without throwing', () => {
    const chunk = 'data: {not valid json\n\n'
    expect(() => parseSseBuffer(chunk)).not.toThrow()
    expect(parseSseBuffer(chunk).events).toEqual([])
  })

  it('skips a JSON payload missing required fields', () => {
    const chunk = `data: ${JSON.stringify({ foo: 'bar' })}\n\n`
    expect(parseSseBuffer(chunk).events).toEqual([])
  })

  it('carries an incomplete trailing event forward as remainder', () => {
    const full = `data: ${JSON.stringify(sampleEvent)}`
    const first = parseSseBuffer(`${full.slice(0, 20)}`)
    expect(first.events).toEqual([])
    expect(first.remainder).toBe(full.slice(0, 20))

    const second = parseSseBuffer(first.remainder + full.slice(20) + '\n\n')
    expect(second.events).toEqual([sampleEvent])
  })

  it('handles a chunk split exactly at the event boundary', () => {
    const chunk1 = `data: ${JSON.stringify(sampleEvent)}\n`
    const chunk2 = `\n`
    const first = parseSseBuffer(chunk1)
    expect(first.events).toEqual([])
    const second = parseSseBuffer(first.remainder + chunk2)
    expect(second.events).toEqual([sampleEvent])
  })
})
