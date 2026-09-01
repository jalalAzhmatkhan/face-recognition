/**
 * Shared types for the "System Parameter" admin menu.
 *
 * Mirrors the backend contracts exposed by `{API_V1_PREFIX}/system-parameters/*`
 * (`backend/app/routers/system_parameters.py`, `backend/app/schemas/
 * system_parameters.py` — NOT to be modified by this feature). Kept as its
 * own copy rather than a shared cross-feature module, per this project's
 * established precedent (see `device-management/types.ts`'s own docstring
 * on this).
 */

export interface EnrollmentQualityParams {
  min_blur_variance: number
  min_brightness: number
  max_brightness: number
}

export interface EnrollmentQualityParamsResponse extends EnrollmentQualityParams {
  updated_by: string | null
  updated_at: string | null
  is_default: boolean
}
