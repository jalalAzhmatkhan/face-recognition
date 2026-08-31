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
