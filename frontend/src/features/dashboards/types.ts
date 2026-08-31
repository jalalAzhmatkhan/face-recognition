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
