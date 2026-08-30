/**
 * Shared types for the device management UI (FE-08, screen-plan S-60).
 *
 * Mirrors the backend contracts exposed by BE-09's
 * `{API_V1_PREFIX}/devices` router (`backend/app/routers/devices.py` — NOT
 * to be modified by this task). Kept as its own copy rather than importing
 * `DeviceSummary` from `live-monitoring/types.ts`: that module's own
 * docstring already explains the project's precedent of one type copy per
 * feature (no shared cross-feature types module exists yet), and this
 * feature needs several fields/bodies live-monitoring has no use for
 * (`credential`, create/update bodies) so importing just `DeviceSummary`
 * from there would still leave those extras defined here anyway.
 */

export type DeviceStatus = 'ONLINE' | 'OFFLINE' | 'DISABLED'

export const DEVICE_STATUSES: DeviceStatus[] = ['ONLINE', 'OFFLINE', 'DISABLED']

export interface DeviceResponse {
  id: string
  name: string
  door_group: string
  status: DeviceStatus
  last_heartbeat_at: string | null
  credential_rotated_at: string | null
  is_stale: boolean
}

/** Returned ONLY by `POST /devices` and `POST /devices/{id}/rotate-credential`
 * — the bootstrap credential appears in this one response and is never
 * retrievable again afterwards (task instructions, BE-09 contract). Modeled
 * as a distinct type from `DeviceResponse` (rather than an optional field on
 * it) so the type system forces every call site that receives one of these
 * two responses to consider the credential, instead of it being an
 * easy-to-miss optional field on the plain list/detail shape. */
export interface DeviceWithCredential extends DeviceResponse {
  credential: string
}

export interface DeviceListResponse {
  items: DeviceResponse[]
  total: number
  limit: number
  offset: number
}

export interface CreateDeviceBody {
  name: string
  door_group: string
}

export interface UpdateDeviceBody {
  name?: string
  door_group?: string
  status?: DeviceStatus
}
