import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  createEnrollment,
  describeApiError,
  listEnrollments,
} from '../features/enrollment-management/api'
import { getCurrentRole } from '../features/enrollment-management/authToken'
import { canCreateEnrollment } from '../features/enrollment-management/roleGating'
import StateBadge from '../features/enrollment-management/StateBadge'
import { ENROLLMENT_STATES } from '../features/enrollment-management/types'
import type { EnrollmentState } from '../features/enrollment-management/types'
import { describeApiError as describeUserApiError, listUsers } from '../features/user-management/api'

const PAGE_SIZE = 20
// Both `GET /users` and `GET /enrollments` cap `limit` at 200 server-side
// (same convention across this codebase's list endpoints) -- the "belum
// pernah dienroll" dropdown below is built from a single unfiltered page
// of each, so an org with >200 ACTIVE users or >200 total enrollment
// sessions could see an incomplete (not incorrect -- just possibly
// missing some eligible users) dropdown. No pagination loop here since
// that's a lot of complexity for a dev-console convenience dropdown;
// revisit if this project ever operates at that scale.
const MAX_LOOKUP = 200

/** States that mean "this user already has an enrollment in progress or
 * completed" -- i.e. every `EnrollmentState` except the two genuinely
 * abandoned ones. Deliberately broader than the frontend's own
 * `TERMINAL_STATES` (which only lists CANCELLED/REVOKED, for a different
 * "no further FSM transition" purpose) -- ENROLLED counts as "blocked"
 * here even though it's also terminal, since a successfully enrolled user
 * should not be offered for re-enrollment. There is no backend rule
 * preventing a second enrollment session for the same user today (no DB
 * uniqueness constraint, no service-level check) -- this dropdown is the
 * enforcement point on the frontend side. */
const BLOCKING_STATES: ReadonlySet<EnrollmentState> = new Set([
  'CREATED',
  'CONSENTED',
  'CAPTURING',
  'CAPTURED',
  'QC_RUNNING',
  'REJECTED_QUALITY',
  'QC_PASSED',
  'EMBEDDING',
  'ENROLLED',
])

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

/** S-30/S-31: enrollment session list + entry point into FE-04's capture
 * wizard. FE-05 scope. */
export default function EnrollmentsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const role = getCurrentRole()

  const [userIdFilter, setUserIdFilter] = useState('')
  const [stateFilter, setStateFilter] = useState<EnrollmentState | ''>('')
  const [offset, setOffset] = useState(0)
  const [appliedUserId, setAppliedUserId] = useState('')

  const [newUserId, setNewUserId] = useState('')
  const [jumpSessionId, setJumpSessionId] = useState('')

  const listQuery = useQuery({
    queryKey: ['enrollments', { userId: appliedUserId, state: stateFilter, offset }],
    queryFn: () =>
      listEnrollments({
        userId: appliedUserId || undefined,
        state: stateFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  // Name lookup for the "Nama User" column below -- a session's user can be
  // of ANY status (not just ACTIVE, unlike `eligibleUsersQuery`'s dropdown
  // data), so this is deliberately a separate, unconditional, unfiltered
  // fetch. Same MAX_LOOKUP dev-console-scale convention as the rest of this
  // file: one bounded page of users, not a lookup per row.
  const userNamesQuery = useQuery({
    queryKey: ['users', 'all-for-name-lookup'],
    queryFn: () => listUsers({ limit: MAX_LOOKUP }),
  })
  const userNameById = useMemo(
    () => new Map((userNamesQuery.data?.items ?? []).map((user) => [user.id, user])),
    [userNamesQuery.data],
  )

  // "Buat Enrollment Baru" dropdown data: ACTIVE users minus anyone with an
  // in-progress-or-completed enrollment session (see BLOCKING_STATES). Only
  // fetched when the create-form is actually visible to this role.
  const canCreate = canCreateEnrollment(role)
  const eligibleUsersQuery = useQuery({
    queryKey: ['users', 'active-for-enrollment'],
    queryFn: () => listUsers({ status: 'ACTIVE', limit: MAX_LOOKUP }),
    enabled: canCreate,
  })
  const allEnrollmentsQuery = useQuery({
    queryKey: ['enrollments', 'all-for-eligibility-check'],
    queryFn: () => listEnrollments({ limit: MAX_LOOKUP }),
    enabled: canCreate,
  })

  const availableUsers = useMemo(() => {
    const blockedUserIds = new Set(
      (allEnrollmentsQuery.data?.items ?? [])
        .filter((session) => BLOCKING_STATES.has(session.state))
        .map((session) => session.user_id),
    )
    return (eligibleUsersQuery.data?.items ?? [])
      .filter((user) => !blockedUserIds.has(user.id))
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
  }, [eligibleUsersQuery.data, allEnrollmentsQuery.data])

  const createMutation = useMutation({
    mutationFn: (userId: string) => createEnrollment(userId),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['enrollments'] })
      setNewUserId('')
      navigate(`/enrollments/${session.id}`)
    },
  })

  const items = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  return (
    <>
      <PagePlaceholder
        title="Enrollment"
        description="Daftar sesi enrollment: filter, pagination, dan aksi berbasis role."
      />

      {canCreate && (
        <section
          style={{
            marginTop: 'var(--space-6)',
            background: 'var(--bg-surface)',
            border: 'var(--border-w) solid var(--border-default)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-sm)',
            padding: 'var(--space-6)',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-3)',
          }}
        >
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Buat Enrollment Baru</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (newUserId.trim()) createMutation.mutate(newUserId.trim())
            }}
            style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}
          >
            <label htmlFor="new-enrollment-user-id" style={{ display: 'none' }}>
              User
            </label>
            <select
              id="new-enrollment-user-id"
              value={newUserId}
              onChange={(event) => setNewUserId(event.target.value)}
              disabled={eligibleUsersQuery.isLoading || allEnrollmentsQuery.isLoading}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                flex: '1 1 280px',
              }}
            >
              <option value="">
                {eligibleUsersQuery.isLoading || allEnrollmentsQuery.isLoading
                  ? 'Memuat daftar user...'
                  : availableUsers.length === 0
                    ? 'Tidak ada user yang bisa dienroll'
                    : 'Pilih user...'}
              </option>
              {availableUsers.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.full_name}
                  {user.external_ref ? ` (${user.external_ref})` : ''}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={!newUserId.trim() || createMutation.isPending}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: newUserId.trim() ? 'pointer' : 'not-allowed',
                opacity: newUserId.trim() ? 1 : 0.5,
              }}
            >
              {createMutation.isPending ? 'Membuat...' : 'Buat Sesi'}
            </button>
          </form>
          <p style={{ margin: 0, color: 'var(--text-muted)', font: 'var(--text-caption)' }}>
            Hanya menampilkan user berstatus ACTIVE yang belum punya sesi enrollment berjalan
            atau selesai (sesi yang dibatalkan/CANCELLED tidak menghalangi user muncul lagi di
            sini).
          </p>
          {eligibleUsersQuery.isError && (
            // `listUsers` throws user-management's OWN `ApiError` class (a
            // different reference than enrollment-management's) -- must use
            // its matching `describeApiError`, same bug/fix already
            // documented in UsersPage.tsx for the mirror-image case.
            <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
              {describeUserApiError(eligibleUsersQuery.error)}
            </p>
          )}
          {allEnrollmentsQuery.isError && (
            <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
              {describeApiError(allEnrollmentsQuery.error)}
            </p>
          )}
          {createMutation.isError && (
            <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
              {describeApiError(createMutation.error)}
            </p>
          )}
        </section>
      )}

      <section
        style={{
          marginTop: 'var(--space-6)',
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-sm)',
          padding: 'var(--space-6)',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setOffset(0)
            setAppliedUserId(userIdFilter.trim())
          }}
          style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}
        >
          <label htmlFor="filter-user-id" style={{ display: 'none' }}>
            Filter User ID
          </label>
          <input
            id="filter-user-id"
            value={userIdFilter}
            onChange={(event) => setUserIdFilter(event.target.value)}
            placeholder="Filter berdasarkan User ID"
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              flex: '1 1 220px',
            }}
          />
          <label htmlFor="filter-state" style={{ display: 'none' }}>
            Filter Status
          </label>
          <select
            id="filter-state"
            value={stateFilter}
            onChange={(event) => {
              setOffset(0)
              setStateFilter(event.target.value as EnrollmentState | '')
            }}
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="">Semua Status</option>
            {ENROLLMENT_STATES.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </select>
          <button
            type="submit"
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-5)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-strong)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            Terapkan Filter
          </button>
        </form>

        {listQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {listQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(listQuery.error)}
          </p>
        )}
        {!listQuery.isLoading && !listQuery.isError && items.length === 0 && (
          <p style={{ color: 'var(--text-secondary)' }}>
            Tidak ada sesi enrollment yang cocok dengan filter ini.
          </p>
        )}

        {items.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: 'var(--border-w) solid var(--border-default)' }}>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Nama User</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Status</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Dibuat</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Aksi</th>
                </tr>
              </thead>
              <tbody>
                {items.map((session) => {
                  const user = userNameById.get(session.user_id)
                  return (
                  <tr
                    key={session.id}
                    style={{ borderBottom: 'var(--border-w) solid var(--border-default)' }}
                  >
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                      {user ? (
                        <Link to={`/enrollments/${session.id}`}>
                          {user.full_name}
                          {user.external_ref ? ` (${user.external_ref})` : ''}
                        </Link>
                      ) : (
                        <Link
                          to={`/enrollments/${session.id}`}
                          style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}
                        >
                          {session.user_id}
                        </Link>
                      )}
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                      <StateBadge state={session.state} />
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--text-secondary)' }}>
                      {formatDate(session.created_at)}
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                      <Link to={`/enrollments/${session.id}`}>Lihat detail</Link>
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-muted)', font: 'var(--text-small)' }}>
            {total > 0
              ? `Menampilkan ${offset + 1}-${Math.min(offset + PAGE_SIZE, total)} dari ${total}`
              : null}
          </span>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-4)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-strong)',
                background: 'var(--bg-surface)',
                opacity: hasPrev ? 1 : 0.5,
                cursor: hasPrev ? 'pointer' : 'not-allowed',
              }}
            >
              Sebelumnya
            </button>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-4)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-strong)',
                background: 'var(--bg-surface)',
                opacity: hasNext ? 1 : 0.5,
                cursor: hasNext ? 'pointer' : 'not-allowed',
              }}
            >
              Berikutnya
            </button>
          </div>
        </div>
      </section>

      <section
        style={{
          marginTop: 'var(--space-6)',
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-sm)',
          padding: 'var(--space-8)',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <h2 style={{ margin: 0 }}>Mulai Capture Enrollment</h2>
        <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
          Masukkan ID sesi enrollment untuk membuka wizard capture 360°
          langsung, tanpa melalui detail sesi.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (jumpSessionId.trim()) {
              navigate(`/enrollments/${jumpSessionId.trim()}/capture`)
            }
          }}
          style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}
        >
          <label htmlFor="enrollment-session-id" style={{ display: 'none' }}>
            ID Sesi Enrollment
          </label>
          <input
            id="enrollment-session-id"
            name="sessionId"
            value={jumpSessionId}
            onChange={(event) => setJumpSessionId(event.target.value)}
            placeholder="ID sesi enrollment"
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              flex: '1 1 240px',
            }}
          />
          <button
            type="submit"
            disabled={!jumpSessionId.trim()}
            style={{
              minHeight: 'var(--touch-target)',
              minWidth: 'var(--touch-target)',
              padding: '0 var(--space-6)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--accent)',
              background: 'var(--accent)',
              color: 'var(--text-inverse)',
              cursor: jumpSessionId.trim() ? 'pointer' : 'not-allowed',
              opacity: jumpSessionId.trim() ? 1 : 0.5,
            }}
          >
            Buka Capture
          </button>
        </form>
      </section>
    </>
  )
}
