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
  external_ref: string
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
