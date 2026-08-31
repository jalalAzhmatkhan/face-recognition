import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import { describeApiError, getUser, offboardUser, updateUser } from '../features/user-management/api'
import { createEnrollment } from '../features/enrollment-management/api'
import { getCurrentRole } from '../lib/authToken'
import { canEditUser, canOffboardUser, canStartEnrollment } from '../features/user-management/roleGating'
import UserStatusBadge from '../features/user-management/UserStatusBadge'
import { USER_STATUSES } from '../features/user-management/types'
import type { UserStatus } from '../features/user-management/types'

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

function surfaceCard(children: ReactNode) {
  return (
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
      {children}
    </section>
  )
}

/** S-11 user detail: edit external_ref/full_name/status (ADMIN/OPERATOR),
 * read-only for VIEWER, "Nonaktifkan" with confirmation, and the
 * "Mulai Enrollment" entry point into FE-05's enrollment flow. FE-03 scope. */
export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const role = getCurrentRole()

  const [externalRef, setExternalRef] = useState('')
  const [fullName, setFullName] = useState('')
  const [status, setStatus] = useState<UserStatus>('ACTIVE')
  const [showOffboardConfirm, setShowOffboardConfirm] = useState(false)
  // Tracks which fetched record the form fields were last seeded from, so a
  // fresh fetch (e.g. after `updateMutation` invalidates the query, or the
  // route param changes) re-seeds the form without clobbering in-progress
  // edits on every render. This is the "adjust state during render" pattern
  // React recommends instead of a useEffect that calls setState
  // (react-hooks/set-state-in-effect) for deriving state from a prop/query.
  const [seededFromUpdatedAt, setSeededFromUpdatedAt] = useState<string | null>(null)

  const detailQuery = useQuery({
    queryKey: ['user', id],
    queryFn: () => getUser(id as string),
    enabled: Boolean(id),
  })

  if (detailQuery.data && detailQuery.data.updated_at !== seededFromUpdatedAt) {
    setSeededFromUpdatedAt(detailQuery.data.updated_at)
    setExternalRef(detailQuery.data.external_ref ?? '')
    setFullName(detailQuery.data.full_name)
    setStatus(detailQuery.data.status)
  }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['user', id] })
    queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  const updateMutation = useMutation({
    mutationFn: () =>
      updateUser(id as string, {
        external_ref: externalRef.trim(),
        full_name: fullName.trim(),
        status,
      }),
    onSuccess: invalidate,
  })

  const offboardMutation = useMutation({
    mutationFn: () => offboardUser(id as string),
    onSuccess: () => {
      setShowOffboardConfirm(false)
      invalidate()
    },
  })

  const enrollMutation = useMutation({
    mutationFn: () => createEnrollment(id as string),
    onSuccess: (session) => navigate(`/enrollments/${session.id}`),
  })

  if (!id) {
    return <PagePlaceholder screenId="S-11" title="User" description="ID user tidak valid." />
  }

  if (detailQuery.isLoading) {
    return (
      <PagePlaceholder screenId="S-11" title="Detail User" description="Memuat data user..." />
    )
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <>
        <PagePlaceholder
          screenId="S-11"
          title="Detail User"
          description={describeApiError(detailQuery.error)}
        />
        <p style={{ marginTop: 'var(--space-4)' }}>
          <Link to="/users">Kembali ke daftar user</Link>
        </p>
      </>
    )
  }

  const user = detailQuery.data
  const canEdit = canEditUser(role)
  const canOffboard = canOffboardUser(role) && user.status !== 'OFFBOARDED'
  const canEnroll = canStartEnrollment(role)
  const anyMutationPending = updateMutation.isPending || offboardMutation.isPending || enrollMutation.isPending
  const hasChanges =
    externalRef.trim() !== (user.external_ref ?? '') ||
    fullName.trim() !== user.full_name ||
    status !== user.status

  return (
    <>
      <header style={{ marginBottom: 'var(--space-4)' }}>
        <p
          className="mono"
          style={{
            font: 'var(--text-caption)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
            margin: 0,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
        >
          S-11
        </p>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          Detail User
          <UserStatusBadge status={user.status} />
        </h1>
        <Link to="/users">Kembali ke daftar user</Link>
      </header>

      {surfaceCard(
        <>
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Informasi User</h2>
          <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: 'var(--space-2) var(--space-4)', margin: 0 }}>
            <dt style={{ color: 'var(--text-secondary)' }}>User ID</dt>
            <dd style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>{user.id}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>Dibuat pada</dt>
            <dd style={{ margin: 0 }}>{formatDate(user.created_at)}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>Diperbarui pada</dt>
            <dd style={{ margin: 0 }}>{formatDate(user.updated_at)}</dd>
          </dl>
        </>,
      )}

      {surfaceCard(
        <>
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>
            {canEdit ? 'Edit User' : 'Data User (read-only)'}
          </h2>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (canEdit && externalRef.trim() && fullName.trim()) updateMutation.mutate()
            }}
            style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', maxWidth: 480 }}
          >
            <label htmlFor="edit-external-ref" style={{ color: 'var(--text-secondary)', font: 'var(--text-caption)' }}>
              External Ref
            </label>
            <input
              id="edit-external-ref"
              value={externalRef}
              onChange={(event) => setExternalRef(event.target.value)}
              disabled={!canEdit}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
              }}
            />

            <label htmlFor="edit-full-name" style={{ color: 'var(--text-secondary)', font: 'var(--text-caption)' }}>
              Nama Lengkap
            </label>
            <input
              id="edit-full-name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              disabled={!canEdit}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
              }}
            />

            <label htmlFor="edit-status" style={{ color: 'var(--text-secondary)', font: 'var(--text-caption)' }}>
              Status
            </label>
            <select
              id="edit-status"
              value={status}
              onChange={(event) => setStatus(event.target.value as UserStatus)}
              disabled={!canEdit}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-3)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--border-default)',
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
              }}
            >
              {USER_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>

            {canEdit && (
              <button
                type="submit"
                disabled={!externalRef.trim() || !fullName.trim() || !hasChanges || anyMutationPending}
                style={{
                  alignSelf: 'flex-start',
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-6)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--accent)',
                  background: 'var(--accent)',
                  color: 'var(--text-inverse)',
                  cursor: hasChanges ? 'pointer' : 'not-allowed',
                  opacity: hasChanges ? 1 : 0.5,
                }}
              >
                {updateMutation.isPending ? 'Menyimpan...' : 'Simpan Perubahan'}
              </button>
            )}
          </form>

          {updateMutation.isError && (
            <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
              {describeApiError(updateMutation.error)}
            </p>
          )}
          {updateMutation.isSuccess && (
            <p style={{ color: 'var(--success)', margin: 0 }}>Perubahan tersimpan.</p>
          )}
        </>,
      )}

      {(canOffboard || canEnroll) &&
        surfaceCard(
          <>
            <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Aksi</h2>

            {canEnroll && (
              <button
                type="button"
                disabled={anyMutationPending}
                onClick={() => enrollMutation.mutate()}
                style={{
                  alignSelf: 'flex-start',
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-5)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--accent)',
                  background: 'var(--accent)',
                  color: 'var(--text-inverse)',
                  cursor: 'pointer',
                }}
              >
                {enrollMutation.isPending ? 'Membuat...' : 'Mulai Enrollment'}
              </button>
            )}

            {canOffboard && !showOffboardConfirm && (
              <button
                type="button"
                disabled={anyMutationPending}
                onClick={() => setShowOffboardConfirm(true)}
                style={{
                  alignSelf: 'flex-start',
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-5)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--danger)',
                  background: 'var(--danger-subtle-bg)',
                  color: 'var(--danger)',
                  cursor: 'pointer',
                }}
              >
                Nonaktifkan User
              </button>
            )}

            {canOffboard && showOffboardConfirm && (
              <div
                style={{
                  border: 'var(--border-w-strong) solid var(--danger)',
                  borderRadius: 'var(--radius-md)',
                  padding: 'var(--space-4)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 'var(--space-3)',
                  background: 'var(--danger-subtle-bg)',
                }}
              >
                <p style={{ margin: 0, color: 'var(--danger)' }}>
                  User akan diset ke status OFFBOARDED dan tidak akan lagi diberi akses meskipun
                  wajahnya cocok (FR-USR-01). Ini mengubah status saja — data biometrik/enrollment
                  tidak dihapus dan status bisa dikembalikan lagi nanti. Lanjutkan?
                </p>
                <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                  <button
                    type="button"
                    disabled={anyMutationPending}
                    onClick={() => offboardMutation.mutate()}
                    style={{
                      minHeight: 'var(--touch-target)',
                      padding: '0 var(--space-5)',
                      borderRadius: 'var(--radius-md)',
                      border: 'var(--border-w) solid var(--danger)',
                      background: 'var(--danger)',
                      color: 'var(--text-inverse)',
                      cursor: 'pointer',
                    }}
                  >
                    {offboardMutation.isPending ? 'Memproses...' : 'Ya, Nonaktifkan'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowOffboardConfirm(false)}
                    style={{
                      minHeight: 'var(--touch-target)',
                      padding: '0 var(--space-5)',
                      borderRadius: 'var(--radius-md)',
                      border: 'var(--border-w) solid var(--border-strong)',
                      background: 'var(--bg-surface)',
                      cursor: 'pointer',
                    }}
                  >
                    Batal
                  </button>
                </div>
              </div>
            )}

            {(offboardMutation.isError || enrollMutation.isError) && (
              <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
                {describeApiError(offboardMutation.error ?? enrollMutation.error)}
              </p>
            )}
          </>,
        )}
    </>
  )
}
