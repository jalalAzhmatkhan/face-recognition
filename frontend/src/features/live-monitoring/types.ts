/**
 * Shared types for the live monitoring UI (FE-06, screen-plan S-40).
 *
 * Mirrors the backend contracts exposed by BE-10/BE-11's
 * `{API_V1_PREFIX}/access-events` + `/stream/access-events` routers
 * (`AccessEventResponse`) and BE-09's `{API_V1_PREFIX}/devices` router
 * (`DeviceResponse`). Kept as a separate copy rather than importing from
 * `user-management`/`enrollment-management` types — this feature has no
 * shared enum with those, and a generic cross-feature types module isn't
 * worth introducing for one field's worth of overlap (same rationale as
 * `UserStatusBadge`'s docstring for not sharing with `StateBadge`).
 */

export type AccessDecision = 'GRANTED' | 'DENIED' | 'UNKNOWN' | 'SPOOF_SUSPECTED'

export const ACCESS_DECISIONS: AccessDecision[] = [
  'GRANTED',
  'DENIED',
  'UNKNOWN',
  'SPOOF_SUSPECTED',
]

/** One access-event row, whether it arrived via SSE or `GET /access-events`
 * — both share this exact JSON shape (backend docstring, BE-11). */
export interface AccessEventPayload {
  id: string
  occurred_at: string
  device_id: string
  decision: AccessDecision
  matched_user_id: string | null
  similarity: number | null
  liveness_score: number | null
  model_version: string | null
  latency_ms: number | null
  /** BE-10's `AccessEventResponse` does serialize this (see
   * `backend/app/schemas/access_events.py`), but there is no backend
   * endpoint to retrieve/presign the referenced `media_objects` row (FE-10
   * gap) -- kept here purely so the S-41 drawer can show a "frame
   * retained, preview not yet available" note rather than nothing at all. */
  frame_media_id: string | null
  door_command_issued: boolean
}

export interface AccessEventListResponse {
  items: AccessEventPayload[]
  total: number
  limit: number
  offset: number
}

export type DeviceStatus = 'ONLINE' | 'OFFLINE' | 'DISABLED'

export interface DeviceSummary {
  id: string
  name: string
  door_group: string
  status: DeviceStatus
  last_heartbeat_at: string | null
  credential_rotated_at: string | null
  is_stale: boolean
}

export interface DeviceListResponse {
  items: DeviceSummary[]
  total: number
  limit: number
  offset: number
}

/** Local (session-only) running totals for the "ringkasan hari ini" panel.
 * SPOOF_SUSPECTED is kept as its own bucket rather than folded into DENIED
 * — NFR-SEC-06 treats it as a distinct security signal operators should be
 * able to see at a glance, separate from ordinary access denials. */
export type TodaySummary = Record<AccessDecision, number>

export const EMPTY_TODAY_SUMMARY: TodaySummary = {
  GRANTED: 0,
  DENIED: 0,
  UNKNOWN: 0,
  SPOOF_SUSPECTED: 0,
}

export type ConnectionStatus = 'connecting' | 'live' | 'reconnecting' | 'disconnected'
