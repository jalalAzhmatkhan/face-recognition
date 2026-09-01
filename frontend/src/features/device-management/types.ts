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

/** Device category (EC-BE-01, TSD-edge-cases.md D-5/D-10). Matches
 * `backend/app/models/enums.py::DeviceClass` and the `device_class` native
 * Postgres enum, and `documentation/operations/camera-placement-guide.md`
 * §5 (which uses these same `door_entry`/`attendance` values). */
export type DeviceClass = 'door_entry' | 'attendance' | 'unknown'

export const DEVICE_CLASSES: DeviceClass[] = ['door_entry', 'attendance', 'unknown']

export interface DeviceResponse {
  id: string
  name: string
  door_group: string
  status: DeviceStatus
  last_heartbeat_at: string | null
  credential_rotated_at: string | null
  is_stale: boolean
  /** EC-BE-01 additions. Optional here (rather than required with a
   * default) so existing test fixtures/mocks built before this task keep
   * compiling unchanged — a real `DeviceResponse` from the backend always
   * includes `device_class` (defaults to `unknown`), only
   * `commissioning_checklist` can be genuinely absent (`null`). */
  device_class?: DeviceClass
  commissioning_checklist?: CommissioningChecklist | null
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
  device_class?: DeviceClass
  commissioning_checklist?: CommissioningChecklist
}

/**
 * `devices.commissioning_checklist jsonb` contract (EC-FE-01), FINALIZED by
 * `documentation/operations/camera-placement-guide.md` §5 (EC-OPS-01, not
 * committed). Backend (`backend/app/schemas/devices.py`) stores this as a
 * loose `dict[str, Any]` on purpose (no DB/Pydantic structural validation
 * yet) — these types are this frontend's own enforcement of that contract,
 * per that schema file's own "tracked as follow-up" comment.
 */
export type ChecklistCategory =
  | 'mounting'
  | 'lighting'
  | 'camera_settings'
  | 'occlusion_policy'
  | 'queue_zone'

export type ChecklistValueType = 'number' | 'boolean' | 'enum' | 'text' | 'photo_ref'

export type ChecklistItemStatus = 'pass' | 'fail' | 'na' | null

export interface ChecklistExpectedRange {
  min: number
  max: number
}

export interface ChecklistItem {
  id: string
  category: ChecklistCategory
  label: string
  applicable_device_classes: DeviceClass[]
  required: boolean
  value_type: ChecklistValueType
  unit?: string | null
  expected_range?: ChecklistExpectedRange | null
  expected_value?: boolean | string | null
  enum_options?: string[] | null
  measured_value: number | boolean | string | null
  status: ChecklistItemStatus
  notes: string | null
  checked_at: string | null
  checked_by_staff_id: string | null
}

export type ZoneShape = 'box' | 'circle' | 'polygon' | null

export interface QueueZone {
  stop_point_marked: boolean
  stop_point_distance_m: number | null
  single_face_zone_defined: boolean
  zone_shape: ZoneShape
  zone_reference_photo_s3_key: string | null
  notes: string | null
}

export type ChecklistOverallStatus = 'pending' | 'passed' | 'failed'

export interface CommissioningChecklist {
  schema_version: '1.0'
  device_class: DeviceClass
  overall_status: ChecklistOverallStatus
  commissioned_at: string | null
  commissioned_by_staff_id: string | null
  commissioned_by_name: string | null
  site_notes: string | null
  checks: ChecklistItem[]
  queue_zone: QueueZone | null
  reverify_due_at: string | null
}
