import { useState } from 'react'
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

const PAGE_SIZE = 20

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
        screenId="S-30/S-31"
        title="Enrollment"
        description="Daftar sesi enrollment: filter, pagination, dan aksi berbasis role."
      />

      {canCreateEnrollment(role) && (
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
              User ID
            </label>
            <input
              id="new-enrollment-user-id"
              value={newUserId}
              onChange={(event) => setNewUserId(event.target.value)}
              placeholder="User ID"
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
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>User ID</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Status</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Dibuat</th>
                  <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Aksi</th>
                </tr>
              </thead>
              <tbody>
                {items.map((session) => (
                  <tr
                    key={session.id}
                    style={{ borderBottom: 'var(--border-w) solid var(--border-default)' }}
                  >
                    <td style={{ padding: 'var(--space-2) var(--space-3)', fontFamily: 'var(--font-mono)' }}>
                      {session.user_id}
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
          (FE-04) langsung, tanpa melalui detail sesi.
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
