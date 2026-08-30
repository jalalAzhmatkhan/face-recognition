import type { AccessEventPayload } from './types'

/**
 * Pure parsing of `text/event-stream` chunks into decoded JSON events —
 * split out from `sseClient.ts` so it can be unit tested without any real
 * network/streaming machinery (mirrors the backend's own reasoning in
 * `access_event_stream.py` for testing the generator apart from the HTTP
 * round trip).
 *
 * The wire format (per `access_event_stream.py`) is minimal SSE: each
 * event is one or more lines ending in a blank line (`\n\n`) separator.
 * We only care about `data: {...}` lines; `: keep-alive` comment lines and
 * blank lines are ignored. A chunk boundary from the network can land
 * anywhere, including mid-line or mid-event, so callers must accumulate
 * `remainder` across calls and feed it back in with the next chunk.
 */
export interface ParsedSseBuffer {
  /** Successfully decoded events, in the order they appeared. */
  events: AccessEventPayload[]
  /** Trailing incomplete text to prepend to the next chunk. */
  remainder: string
}

function isAccessEventPayload(value: unknown): value is AccessEventPayload {
  if (value === null || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.id === 'string' && typeof candidate.decision === 'string'
}

/**
 * Feeds one more raw text chunk into an in-progress SSE buffer and returns
 * the events completed by it, plus whatever's left over for next time.
 * Malformed JSON in a `data:` line is skipped (logged nowhere — this is a
 * pure function) rather than thrown, per task instructions ("abaikan JSON
 * yang gagal parse, jangan crash").
 */
export function parseSseBuffer(buffer: string): ParsedSseBuffer {
  const events: AccessEventPayload[] = []
  // SSE events are separated by a blank line. Split greedily; the final
  // element is either '' (buffer ended exactly on a boundary) or an
  // incomplete tail to carry forward as `remainder`.
  const blocks = buffer.split('\n\n')
  const remainder = blocks.pop() ?? ''

  for (const block of blocks) {
    const dataLines = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice('data:'.length).trimStart())
    if (dataLines.length === 0) continue // e.g. ": keep-alive" or blank

    const raw = dataLines.join('\n')
    try {
      const parsed: unknown = JSON.parse(raw)
      if (isAccessEventPayload(parsed)) {
        events.push(parsed)
      }
    } catch {
      // malformed payload — skip, don't crash the stream
    }
  }

  return { events, remainder }
}
