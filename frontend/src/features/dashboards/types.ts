/**
 * Shared types for the operations dashboard (FE-07, screen-plan S-02).
 *
 * Mirrors three separate backend contracts this feature reads from
 * (`AccessEventResponse`/BE-10-11, `ModelVersionResponse`/BE-13,
 * `EnrollmentResponse`/BE-05) — kept as its own copy per this project's
 * established per-feature duplication precedent (see
 * `training-models/types.ts`'s own docstring on this) rather than importing
 * from `live-monitoring`/`training-models`/`enrollment-management`.
 */

export type AccessDecision = 'GRANTED' | 'DENIED' | 'UNKNOWN' | 'SPOOF_SUSPECTED'

export const ACCESS_DECISIONS: AccessDecision[] = [
  'GRANTED',
  'DENIED',
  'UNKNOWN',
  'SPOOF_SUSPECTED',
]

export interface AccessEventListResponse {
  items: unknown[]
  total: number
  limit: number
  offset: number
}

/** Today's raw counts per decision — everything else (unknown rate, grants
 * total, etc.) is derived from these four numbers. */
export type TodayCounts = Record<AccessDecision, number>

export const EMPTY_TODAY_COUNTS: TodayCounts = {
  GRANTED: 0,
  DENIED: 0,
  UNKNOWN: 0,
  SPOOF_SUSPECTED: 0,
}

/** One day's GRANTED/DENIED counts for the 14-day trend chart (screen-plan
 * "grafik garis grants/denies 14 hari"). `dateIso` is the local-midnight
 * `YYYY-MM-DD` this bucket covers. */
export interface DailyDecisionCount {
  dateIso: string
  granted: number
  denied: number
}

export type ModelStage = 'CANDIDATE' | 'PRODUCTION' | 'RETIRED'

export interface ModelVersionResponse {
  version: string
  mlflow_run_id: string
  stage: ModelStage
  recall: number | null
  f1: number | null
  precision: number | null
  latency_ms_p95: number | null
  promoted_by: string | null
  promoted_at: string | null
}

export interface ModelVersionListResponse {
  items: ModelVersionResponse[]
}

/** Enrollment session state machine (FSD-AI.md §8) — same 11 values as
 * `enrollment-management/types.ts`. */
export type EnrollmentState =
  | 'CREATED'
  | 'CONSENTED'
  | 'CAPTURING'
  | 'CAPTURED'
  | 'QC_RUNNING'
  | 'REJECTED_QUALITY'
  | 'QC_PASSED'
  | 'EMBEDDING'
  | 'ENROLLED'
  | 'CANCELLED'
  | 'REVOKED'

/** The "happy path" the funnel visualizes (screen-plan's literal framing:
 * "CREATED→ENROLLED"). `REJECTED_QUALITY`/`CANCELLED`/`REVOKED` are
 * terminal ALTERNATE states, not steps on this path — deliberately
 * excluded from the funnel bars themselves, same reasoning
 * `enrollment-management/types.ts::TERMINAL_STATES` already documents for
 * why those three are tracked separately from the main flow. */
export const ENROLLMENT_FUNNEL_STATES: EnrollmentState[] = [
  'CREATED',
  'CONSENTED',
  'CAPTURING',
  'CAPTURED',
  'QC_RUNNING',
  'QC_PASSED',
  'EMBEDDING',
  'ENROLLED',
]

export interface EnrollmentListResponse {
  items: unknown[]
  total: number
  limit: number
  offset: number
}

export interface EnrollmentFunnelStage {
  state: EnrollmentState
  count: number
}

/**
 * EC-FE-01 (TSD-edge-cases.md D-1) — recognition-pipeline reject funnel,
 * distinct from the enrollment funnel above. Mirrors backend
 * `RejectStage`/`condition_flags`/`device_class` (EC-BE-01 migration,
 * `backend/app/models/enums.py`) filled in by ai-inference (EC-IN-01).
 */
export type RejectStage = 'detection' | 'liveness' | 'quality_gate' | 'threshold' | 'policy'

export const REJECT_STAGES: RejectStage[] = [
  'detection',
  'liveness',
  'quality_gate',
  'threshold',
  'policy',
]

/** Canonical condition-flag keys (TSD-edge-cases.md D-1/D-3) — booleans on
 * `access_events.condition_flags jsonb`. */
export type ConditionFlagKey = 'masked' | 'dark' | 'blurry' | 'low_res' | 'sunglasses'

export const CONDITION_FLAG_KEYS: ConditionFlagKey[] = [
  'masked',
  'dark',
  'blurry',
  'low_res',
  'sunglasses',
]

/** Device category (EC-BE-01) — note the ENUM VALUES are `door_entry` /
 * `attendance` / `unknown` (see `backend/app/models/enums.py::DeviceClass`
 * and the `device_class` native-enum migration), NOT the
 * `access_control`/`attendance` terms used by
 * `documentation/operations/camera-placement-guide.md` §5 (a pre-existing
 * naming mismatch between that ops doc and the actual EC-BE-01
 * implementation — this FE follows the real backend enum, and the
 * commissioning-checklist code treats `door_entry` as that doc's
 * `access_control`). */
export type DeviceClass = 'door_entry' | 'attendance' | 'unknown'

export const DEVICE_CLASSES: DeviceClass[] = ['door_entry', 'attendance', 'unknown']

/** One row of `GET /access-events` as needed for the client-side funnel
 * breakdown below — a subset of the backend's full `AccessEventResponse`
 * (see `backend/app/schemas/access_events.py`). Kept as its own minimal
 * shape (not the full payload `live-monitoring/types.ts::AccessEventPayload`
 * has) since this panel only ever reads these four fields. */
export interface AccessEventSample {
  id: string
  decision: AccessDecision
  reject_stage: RejectStage | null
  condition_flags: Record<string, boolean> | null
  device_class: DeviceClass | null
}

export interface AccessEventSampleResponse {
  items: AccessEventSample[]
  total: number
  limit: number
  offset: number
}

/** One bucket in any of the three EC-FE-01 breakdowns — a label (reject
 * stage / condition flag / device class) plus its count and share of the
 * sample. */
export interface FunnelBreakdownRow {
  key: string
  count: number
  pct: number
}
