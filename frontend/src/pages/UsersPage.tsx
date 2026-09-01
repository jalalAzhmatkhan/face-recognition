import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  createUser,
  describeApiError,
  listUsers,
  offboardUser,
  setUserStatus,
} from '../features/user-management/api'
import { createEnrollment, describeApiError as describeEnrollmentApiError } from '../features/enrollment-management/api'
import { getCurrentRole } from '../lib/authToken'
import {
  canChangeUserStatus,
  canCreateUser,
  canOffboardUser,
  canStartEnrollment,
} from '../features/user-management/roleGating'
import UserStatusBadge from '../features/user-management/UserStatusBadge'
import ReenrollDueBadge from '../features/user-management/ReenrollDueBadge'
import UserActionsMenu from '../features/user-management/UserActionsMenu'
import { USER_STATUSES } from '../features/user-management/types'
import type { UserStatus } from '../features/user-management/types'

const PAGE_SIZE = 20

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

/** S-10 user list: filter/pagination, create, quick status changes, and the
 * entry point into a new enrollment session for a user. FE-03 scope. */
export default function UsersPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const role = getCurrentRole()

  const [statusFilter, setStatusFilter] = useState<UserStatus | ''>('')
  const [offset, setOffset] = useState(0)

  const [newExternalRef, setNewExternalRef] = useState('')
  const [newFullName, setNewFullName] = useState('')

  const [offboardTargetId, setOffboardTargetId] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['users', { status: statusFilter, offset }],
    queryFn: () =>
      listUsers({
        status: statusFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['users'] })

  const createMutation = useMutation({
    mutationFn: () => createUser({ external_ref: newExternalRef.trim(), full_name: newFullName.trim() }),
    onSuccess: () => {
      setNewExternalRef('')
      setNewFullName('')
      invalidate()
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: UserStatus }) => setUserStatus(id, status),
    onSuccess: invalidate,
  })

  const offboardMutation = useMutation({
    mutationFn: (id: string) => offboardUser(id),
    onSuccess: () => {
      setOffboardTargetId(null)
      invalidate()
    },
  })

  const enrollMutation = useMutation({
    mutationFn: (userId: string) => createEnrollment(userId),
    onSuccess: (session) => navigate(`/enrollments/${session.id}`),
  })

  const items = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  const canCreate = canCreateUser(role)
  const canQuickChangeStatus = canChangeUserStatus(role)
  const canOffboard = canOffboardUser(role)
  const canEnroll = canStartEnrollment(role)

  const anyMutationPending =
    createMutation.isPending ||
    statusMutation.isPending ||
    offboardMutation.isPending ||
    enrollMutation.isPending

  return (
    <>
      <PagePlaceholder
        title="Users"
        description="Daftar user terotorisasi: status ACTIVE/SUSPENDED/OFFBOARDED tidak pernah diberi akses biometrik."
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
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Tambah User Baru</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (newExternalRef.trim() && newFullName.trim()) createMutation.mutate()
            }}
            style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}
          >
            <label htmlFor="new-user-external-ref" style={{ display: 'none' }}>
              External Ref
            </label>
            <input
              id="new-user-external-ref"
              value={newExternalRef}
              onChange={(event) => setNewExternalRef(event.target.value)}
              placeholder="External Ref (mis. NIK/ID Karyawan)"
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
                flex: '1 1 220px',
              }}
            />
            <label htmlFor="new-user-full-name" style={{ display: 'none' }}>
              Nama Lengkap
            </label>
            <input
              id="new-user-full-name"
              value={newFullName}
              onChange={(event) => setNewFullName(event.target.value)}
              placeholder="Nama Lengkap"
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
                flex: '1 1 220px',
              }}
            />
            <button
              type="submit"
              disabled={!newExternalRef.trim() || !newFullName.trim() || createMutation.isPending}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: newExternalRef.trim() && newFullName.trim() ? 'pointer' : 'not-allowed',
                opacity: newExternalRef.trim() && newFullName.trim() ? 1 : 0.5,
              }}
            >
              {createMutation.isPending ? 'Menyimpan...' : 'Tambah User'}
            </button>
          </form>
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
          onSubmit={(event) => event.preventDefault()}
          style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}
        >
          <label htmlFor="filter-status" style={{ display: 'none' }}>
            Filter Status
          </label>
          <select
            id="filter-status"
            value={statusFilter}
            onChange={(event) => {
              setOffset(0)
              setStatusFilter(event.target.value as UserStatus | '')
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
            {USER_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </form>

        {listQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {listQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(listQuery.error)}
          </p>
        )}
        {!listQuery.isLoading && !listQuery.isError && items.length === 0 && (
          <p style={{ color: 'var(--text-secondary)' }}>
            Tidak ada user yang cocok dengan filter ini.
          </p>
        )}

        {(statusMutation.isError || offboardMutation.isError) && (
          <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
            {describeApiError(statusMutation.error ?? offboardMutation.error)}
          </p>
        )}

        {enrollMutation.isError && (
          // `createEnrollment` throws enrollment-management's own `ApiError`
          // class, a DIFFERENT class reference than user-management's
          // `ApiError` -- found live: passing it through user-management's
          // `describeApiError` failed its `instanceof ApiError` check
          // silently (it still matches `instanceof Error` since ApiError
          // extends Error) and fell back to the raw
          // "Request to ... failed with 409" message instead of the
          // backend's actual RFC 9457 `detail` ("user is not ACTIVE...").
          <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
            {describeEnrollmentApiError(enrollMutation.error)}
          </p>
        )}

        {items.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: 'var(--border-w) solid var(--border-default)' }}>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>External Ref</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Nama Lengkap</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Status</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Dibuat</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Aksi</th>
                </tr>
              </thead>
              <tbody>
                {items.map((user) => (
                  <tr key={user.id} style={{ borderBottom: 'var(--border-w) solid var(--border-default)' }}>
                    <td style={{ padding: 'var(--space-2) var(--space-3)', fontFamily: 'var(--font-mono)' }}>
                      {user.external_ref}
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>{user.full_name}</td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                        <UserStatusBadge status={user.status} />
                        <ReenrollDueBadge user={user} />
                      </div>
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--text-secondary)' }}>
                      {formatDate(user.created_at)}
                    </td>
                    <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                      <UserActionsMenu
                        user={user}
                        canQuickChangeStatus={canQuickChangeStatus}
                        canOffboard={canOffboard}
                        canEnroll={canEnroll}
                        anyMutationPending={anyMutationPending}
                        isOffboardTarget={offboardTargetId === user.id}
                        isOffboardPending={offboardMutation.isPending}
                        onStatusChange={(status) => statusMutation.mutate({ id: user.id, status })}
                        onRequestOffboard={() => setOffboardTargetId(user.id)}
                        onCancelOffboard={() => setOffboardTargetId(null)}
                        onConfirmOffboard={() => offboardMutation.mutate(user.id)}
                        onEnroll={() => enrollMutation.mutate(user.id)}
                      />
                    </td>
                  </tr>
                ))}
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
    </>
  )
}
