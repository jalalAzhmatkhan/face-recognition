import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  cancelEnrollment,
  describeApiError,
  getEnrollment,
  grantConsent,
  revokeEnrollment,
  startRecapture,
} from '../features/enrollment-management/api'
import { getCurrentRole } from '../features/enrollment-management/authToken'
import { humanizeReasons } from '../features/enrollment-management/reasonHumanizer'
import {
  canCancel,
  canGrantConsent,
  canRecapture,
  canRevoke,
} from '../features/enrollment-management/roleGating'
import StateBadge from '../features/enrollment-management/StateBadge'

const REVOKE_CONFIRM_TEXT = 'REVOKE'

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

/** S-31 enrollment detail: qc_report (humanized), and role/state-gated
 * actions (consent, re-capture, cancel, revoke). FE-05 scope. */
export default function EnrollmentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const role = getCurrentRole()

  const [consentVersion, setConsentVersion] = useState('')
  const [revokeConfirmText, setRevokeConfirmText] = useState('')
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)

  const detailQuery = useQuery({
    queryKey: ['enrollment', id],
    queryFn: () => getEnrollment(id as string),
    enabled: Boolean(id),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['enrollment', id] })
    queryClient.invalidateQueries({ queryKey: ['enrollments'] })
  }

  const consentMutation = useMutation({
    mutationFn: (version: string) => grantConsent(id as string, version),
    onSuccess: () => {
      setConsentVersion('')
      invalidate()
    },
  })

  const recaptureMutation = useMutation({
    mutationFn: () => startRecapture(id as string),
    onSuccess: () => {
      invalidate()
      navigate(`/enrollments/${id}/capture`)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelEnrollment(id as string),
    onSuccess: invalidate,
  })

  const revokeMutation = useMutation({
    mutationFn: () => revokeEnrollment(id as string),
    onSuccess: () => {
      setShowRevokeConfirm(false)
      setRevokeConfirmText('')
      invalidate()
    },
  })

  if (!id) {
    return (
      <PagePlaceholder
        screenId="S-31"
        title="Enrollment"
        description="ID sesi enrollment tidak valid."
      />
    )
  }

  if (detailQuery.isLoading) {
    return (
      <PagePlaceholder
        screenId="S-31"
        title="Detail Enrollment"
        description="Memuat data sesi enrollment..."
      />
    )
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <>
        <PagePlaceholder
          screenId="S-31"
          title="Detail Enrollment"
          description={describeApiError(detailQuery.error)}
        />
        <p style={{ marginTop: 'var(--space-4)' }}>
          <Link to="/enrollments">Kembali ke daftar enrollment</Link>
        </p>
      </>
    )
  }

  const session = detailQuery.data
  const qc = session.qc_report
  const topLevelReasons = humanizeReasons(qc?.reasons)

  const showConsent = canGrantConsent(session.state, role)
  const showRecapture = canRecapture(session.state, role)
  const showCancel = canCancel(session.state, role)
  const showRevoke = canRevoke(session.state, role)
  const anyMutationPending =
    consentMutation.isPending ||
    recaptureMutation.isPending ||
    cancelMutation.isPending ||
    revokeMutation.isPending

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
          S-31
        </p>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          Detail Enrollment
          <StateBadge state={session.state} />
        </h1>
        <Link to="/enrollments">Kembali ke daftar enrollment</Link>
      </header>

      {surfaceCard(
        <>
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Informasi Sesi</h2>
          <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: 'var(--space-2) var(--space-4)', margin: 0 }}>
            <dt style={{ color: 'var(--text-secondary)' }}>Session ID</dt>
            <dd style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>{session.id}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>User ID</dt>
            <dd style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>{session.user_id}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>Dibuat oleh</dt>
            <dd style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>{session.created_by ?? '—'}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>Dibuat pada</dt>
            <dd style={{ margin: 0 }}>{formatDate(session.created_at)}</dd>
            <dt style={{ color: 'var(--text-secondary)' }}>Diperbarui pada</dt>
            <dd style={{ margin: 0 }}>{formatDate(session.updated_at)}</dd>
          </dl>
        </>,
      )}

      {qc &&
        surfaceCard(
          <>
            <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Hasil Quality Check</h2>
            <p style={{ margin: 0 }}>
              Status:{' '}
              <strong style={{ color: qc.overall === 'PASS' ? 'var(--success)' : 'var(--danger)' }}>
                {qc.overall}
              </strong>{' '}
              &middot; Coverage: {(qc.coverage_ratio * 100).toFixed(0)}%
            </p>

            {topLevelReasons.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 'var(--space-5)', color: 'var(--danger)' }}>
                {topLevelReasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            )}

            {qc.positions.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', borderBottom: 'var(--border-w) solid var(--border-default)' }}>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Posisi</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Hasil</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>Alasan</th>
                    </tr>
                  </thead>
                  <tbody>
                    {qc.positions.map((position) => (
                      <tr key={position.position} style={{ borderBottom: 'var(--border-w) solid var(--border-default)' }}>
                        <td style={{ padding: 'var(--space-2) var(--space-3)', fontFamily: 'var(--font-mono)' }}>
                          {position.position}
                        </td>
                        <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                          <span style={{ color: position.passed ? 'var(--success)' : 'var(--danger)' }}>
                            {position.passed ? 'Lolos' : 'Gagal'}
                          </span>
                        </td>
                        <td style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--text-secondary)' }}>
                          {position.reasons.length > 0
                            ? humanizeReasons(position.reasons).join('; ')
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>,
        )}

      {(showConsent || showRecapture || showCancel || showRevoke) &&
        surfaceCard(
          <>
            <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Aksi</h2>

            {showConsent && (
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (consentVersion.trim()) consentMutation.mutate(consentVersion.trim())
                }}
                style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}
              >
                <label htmlFor="consent-version" style={{ display: 'none' }}>
                  Versi Consent
                </label>
                <input
                  id="consent-version"
                  value={consentVersion}
                  onChange={(event) => setConsentVersion(event.target.value)}
                  placeholder="Versi teks consent, mis. v1.0"
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
                  disabled={!consentVersion.trim() || anyMutationPending}
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-5)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--accent)',
                    background: 'var(--accent)',
                    color: 'var(--text-inverse)',
                    cursor: consentVersion.trim() ? 'pointer' : 'not-allowed',
                  }}
                >
                  Catat Consent
                </button>
              </form>
            )}

            {showRecapture && (
              <button
                type="button"
                disabled={anyMutationPending}
                onClick={() => recaptureMutation.mutate()}
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
                {recaptureMutation.isPending ? 'Memulai...' : 'Mulai / Ulangi Capture'}
              </button>
            )}

            {showCancel && (
              <button
                type="button"
                disabled={anyMutationPending}
                onClick={() => {
                  if (window.confirm('Batalkan sesi enrollment ini? Tindakan ini tidak bisa diurungkan.')) {
                    cancelMutation.mutate()
                  }
                }}
                style={{
                  alignSelf: 'flex-start',
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-5)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--warning)',
                  background: 'var(--warning-subtle-bg)',
                  color: 'var(--warning)',
                  cursor: 'pointer',
                }}
              >
                Batalkan Sesi
              </button>
            )}

            {showRevoke && !showRevokeConfirm && (
              <button
                type="button"
                disabled={anyMutationPending}
                onClick={() => setShowRevokeConfirm(true)}
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
                Cabut (Revoke) Enrollment
              </button>
            )}

            {showRevoke && showRevokeConfirm && (
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
                  Tindakan ini akan mencabut enrollment secara permanen: embedding dan media di
                  S3 akan dihapus, dan user tidak akan lagi bisa dikenali sistem. Ketik{' '}
                  <strong>{REVOKE_CONFIRM_TEXT}</strong> untuk melanjutkan.
                </p>
                <label htmlFor="revoke-confirm-text" style={{ display: 'none' }}>
                  Ketik {REVOKE_CONFIRM_TEXT} untuk konfirmasi
                </label>
                <input
                  id="revoke-confirm-text"
                  value={revokeConfirmText}
                  onChange={(event) => setRevokeConfirmText(event.target.value)}
                  placeholder={REVOKE_CONFIRM_TEXT}
                  style={{
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-3)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--danger)',
                  }}
                />
                <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                  <button
                    type="button"
                    disabled={revokeConfirmText !== REVOKE_CONFIRM_TEXT || anyMutationPending}
                    onClick={() => revokeMutation.mutate()}
                    style={{
                      minHeight: 'var(--touch-target)',
                      padding: '0 var(--space-5)',
                      borderRadius: 'var(--radius-md)',
                      border: 'var(--border-w) solid var(--danger)',
                      background: 'var(--danger)',
                      color: 'var(--text-inverse)',
                      cursor: revokeConfirmText === REVOKE_CONFIRM_TEXT ? 'pointer' : 'not-allowed',
                      opacity: revokeConfirmText === REVOKE_CONFIRM_TEXT ? 1 : 0.5,
                    }}
                  >
                    {revokeMutation.isPending ? 'Mencabut...' : 'Konfirmasi Cabut Enrollment'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowRevokeConfirm(false)
                      setRevokeConfirmText('')
                    }}
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

            {(consentMutation.isError ||
              recaptureMutation.isError ||
              cancelMutation.isError ||
              revokeMutation.isError) && (
              <p role="alert" style={{ color: 'var(--danger)', margin: 0 }}>
                {describeApiError(
                  consentMutation.error ??
                    recaptureMutation.error ??
                    cancelMutation.error ??
                    revokeMutation.error,
                )}
              </p>
            )}
          </>,
        )}
    </>
  )
}
