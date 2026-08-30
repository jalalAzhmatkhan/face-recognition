/**
 * Shared types for the training & model management UI (FE-09, screen-plan
 * S-50/S-51/S-52).
 *
 * Mirrors the backend contracts exposed by BE-13's
 * `{API_V1_PREFIX}/training/jobs/*` and `{API_V1_PREFIX}/models/*` routers
 * (`backend/app/routers/training.py`, `backend/app/schemas/training.py` —
 * NOT to be modified by this task). Kept as its own copy rather than a
 * shared cross-feature module, per this project's established precedent
 * (see `device-management/types.ts`'s own docstring on this).
 */

export type ModelStage = 'CANDIDATE' | 'PRODUCTION' | 'RETIRED'

export const MODEL_STAGES: ModelStage[] = ['CANDIDATE', 'PRODUCTION', 'RETIRED']

export type TrainingJobStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

/** Statuses a job is still "in flight" in — polling continues while a job's
 * status is one of these (S-50/S-51 task instructions), and stops the
 * moment it reaches SUCCEEDED or FAILED. */
export const IN_FLIGHT_JOB_STATUSES: TrainingJobStatus[] = ['PENDING', 'RUNNING']

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

export interface TrainingJobResponse {
  id: string
  model_version: string | null
  benchmark_id: string
  status: TrainingJobStatus
  triggered_by: string
  created_at: string
  completed_at: string | null
  error_message: string | null
  mlflow_run_id: string | null
}

/** `GET /training/jobs` (BE-15) — server-side history, newest first. */
export interface TrainingJobListResponse {
  items: TrainingJobResponse[]
  total: number
  limit: number
  offset: number
}

export interface CreateTrainingJobBody {
  model_version: string
  benchmark_id: string
}

export interface ModelPromoteBody {
  /** MUST be sent as `true` — FR-TRN-05's human-in-the-loop gate rejects
   * anything else with a 422 (`ConfirmationRequiredError`). */
  confirm: boolean
}

export interface ModelPromoteResponse {
  version: string
  stage: ModelStage
  promoted_by: string
  promoted_at: string
}
