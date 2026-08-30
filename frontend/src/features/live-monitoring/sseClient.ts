import { buildAccessEventStreamUrl } from './api'
import { parseSseBuffer } from './sseParser'
import type { AccessDecision, AccessEventPayload, ConnectionStatus } from './types'
import { getAccessToken, refreshAccessToken } from '../../lib/authToken'

/**
 * fetch()-based SSE client for `GET /stream/access-events` (BE-11).
 *
 * The browser's built-in `EventSource` cannot send a custom `Authorization`
 * header (task instructions), so this streams the response body manually
 * via `fetch()` + `ReadableStream`, parsing `data: {...}\n\n` lines with
 * `parseSseBuffer`. On a 401 it makes one reactive refresh-and-retry
 * attempt, same as `authFetch` elsewhere in this app. On any other
 * disconnect/error it auto-reconnects with exponential backoff (1s → 30s
 * cap) until `close()` is called.
 */

const INITIAL_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30_000

export interface AccessEventStreamOptions {
  deviceId?: string
  decision?: AccessDecision
  onEvent: (event: AccessEventPayload) => void
  onStatusChange: (status: ConnectionStatus) => void
}

export interface AccessEventStreamHandle {
  close: () => void
}

export function openAccessEventStream(
  options: AccessEventStreamOptions,
): AccessEventStreamHandle {
  const url = buildAccessEventStreamUrl({
    deviceId: options.deviceId,
    decision: options.decision,
  })

  let closed = false
  let controller: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let backoffMs = INITIAL_BACKOFF_MS

  async function connect(isReconnect: boolean): Promise<void> {
    if (closed) return
    options.onStatusChange(isReconnect ? 'reconnecting' : 'connecting')

    controller = new AbortController()
    try {
      let token = getAccessToken()
      let response = await fetch(url, {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: controller.signal,
      })

      if (response.status === 401) {
        token = await refreshAccessToken()
        if (closed) return
        if (token) {
          response = await fetch(url, {
            headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
            signal: controller.signal,
          })
        }
      }

      if (!response.ok || !response.body) {
        throw new Error(`stream connect failed with status ${response.status}`)
      }

      // Connected — reset backoff for the next time this drops.
      backoffMs = INITIAL_BACKOFF_MS
      options.onStatusChange('live')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (!closed) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parsed = parseSseBuffer(buffer)
        buffer = parsed.remainder
        for (const event of parsed.events) options.onEvent(event)
      }

      if (!closed) scheduleReconnect()
    } catch (error) {
      if (closed) return
      if (error instanceof DOMException && error.name === 'AbortError') return
      scheduleReconnect()
    }
  }

  function scheduleReconnect(): void {
    if (closed) return
    options.onStatusChange('reconnecting')
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS)
      void connect(true)
    }, backoffMs)
  }

  void connect(false)

  return {
    close(): void {
      if (closed) return
      closed = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      controller?.abort()
      options.onStatusChange('disconnected')
    },
  }
}
