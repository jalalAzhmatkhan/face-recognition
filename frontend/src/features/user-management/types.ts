/**
 * Shared types for the user management UI (FE-03).
 *
 * Mirrors the backend contracts exposed by BE-04's `{API_V1_PREFIX}/users`
 * router (`UserResponse`, `status` enum ACTIVE/SUSPENDED/OFFBOARDED).
 */

export type UserStatus = 'ACTIVE' | 'SUSPENDED' | 'OFFBOARDED'

export const USER_STATUSES: UserStatus[] = ['ACTIVE', 'SUSPENDED', 'OFFBOARDED']

export interface UserResponse {
  id: string
  /** Nullable on the backend (`app/schemas/users.py::UserResponse`) even
   * though `CreateUserBody.external_ref` below is required to create one —
   * kept optional here to match, not because the UI has any path that sets
   * it to null itself (found live, FE-10: `UserDetailPage` crashed calling
   * `.trim()` on this when it was null). */
  external_ref: string | null
  full_name: string
  status: UserStatus
  created_at: string
  updated_at: string
  /**
   * EC-FE-03 GAP (backend): `users.reenroll_due` / `.reenroll_due_reason` /
   * `.reenroll_due_marked_at` exist on the `users` table since EC-BE-05
   * (`backend/app/models/user.py`), but `UserResponse`
   * (`backend/app/schemas/users.py`) does NOT expose them yet — confirmed by
   * reading that file directly, not inferred. `GET /users` / `GET /users/{id}`
   * therefore never return these fields today, so they are typed here as
   * optional and every read site MUST treat `undefined` the same as
   * `false`/`null` (see `isReenrollDue` below). Widening the backend
   * response schema is intentionally NOT done by this task — out of scope
   * for a frontend-only assignment. Follow-up: once a backend task adds
   * these three fields to `UserResponse`, this UI starts showing real data
   * with no FE change needed.
   */
  reenroll_due?: boolean
  reenroll_due_reason?: string | null
  reenroll_due_marked_at?: string | null
}

/** Safe accessor for `UserResponse.reenroll_due` — collapses the "backend
 * doesn't send this field yet" `undefined` case to `false` in one place so
 * call sites never have to remember the gap noted above. */
export function isReenrollDue(user: Pick<UserResponse, 'reenroll_due'>): boolean {
  return user.reenroll_due === true
}

/**
 * EC-FE-03 GAP (backend): `identity_similarity_flags` (EC-BE-04) has a model
 * + repository (`backend/app/models/identity_similarity_flag.py`,
 * `backend/app/repositories/identity_similarity_flags.py`) but, confirmed by
 * grepping `backend/app/routers/`, has NO HTTP router — there is no endpoint
 * to fetch this data from today. This type is defined ahead of time so the
 * ADMIN UI can be wired up with a single follow-up change (add an `api.ts`
 * function + swap the placeholder section for a real fetch) once a backend
 * task adds the endpoint. Nothing in this feature calls a real endpoint for
 * this today — see `IdentitySimilarityPanel.tsx`.
 */
export interface IdentitySimilarityFlag {
  user_a: string
  user_b: string
  score: number
  flagged_at: string
}

export interface UserListResponse {
  items: UserResponse[]
  total: number
  limit: number
  offset: number
}

export interface CreateUserBody {
  external_ref: string
  full_name: string
}

export interface UpdateUserBody {
  external_ref?: string
  full_name?: string
  status?: UserStatus
}
