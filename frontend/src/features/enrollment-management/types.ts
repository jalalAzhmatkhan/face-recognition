/**
 * Shared types for the enrollment management UI (FE-05).
 *
 * Mirrors the backend contracts in `backend/app/schemas/enrollments.py`
 * (BE-05) and the QC report shape produced by
 * `ai-training/src/ai_training/quality/report.py` + `worker/tasks.py`
 * (TR-02, FR-ENR-06) that is stored verbatim into `qc_report` (jsonb).
 */

/** Enrollment session state machine (FSD-AI.md §8). */
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

export const ENROLLMENT_STATES: EnrollmentState[] = [
  'CREATED',
  'CONSENTED',
  'CAPTURING',
  'CAPTURED',
  'QC_RUNNING',
  'REJECTED_QUALITY',
  'QC_PASSED',
  'EMBEDDING',
  'ENROLLED',
  'CANCELLED',
  'REVOKED',
]

/** Terminal states — no further transition is ever legal from these. */
export const TERMINAL_STATES: readonly EnrollmentState[] = ['CANCELLED', 'REVOKED']

/** Staff console RBAC roles (FR-USR-02). */
export type StaffRole = 'ADMIN' | 'OPERATOR' | 'VIEWER'

export const STAFF_ROLES: StaffRole[] = ['ADMIN', 'OPERATOR', 'VIEWER']

/** Pass/fail outcome for one of the 12 clock positions (QC pipeline). */
export interface QcPositionResult {
  /** "01".."12" */
  position: string
  passed: boolean
  reasons: string[]
  best_score: number | null
}

/**
 * `qc_report` jsonb column, present when state is REJECTED_QUALITY or
 * ENROLLED. `reasons` is a top-level, session-level list (e.g.
 * "video_missing"/"video_undecodable" when the whole video could not be
 * processed at all, before any per-position result exists) — separate from
 * each position's own `reasons`.
 */
export interface QcReport {
  session_id: string
  overall: string
  coverage_ratio: number
  positions: QcPositionResult[]
  reasons?: string[]
  generated_at?: string
}

export interface EnrollmentResponse {
  id: string
  user_id: string
  state: EnrollmentState
  qc_report: QcReport | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface EnrollmentListResponse {
  items: EnrollmentResponse[]
  total: number
  limit: number
  offset: number
}

export interface RevocationResponse {
  id: string
  state: EnrollmentState
}
