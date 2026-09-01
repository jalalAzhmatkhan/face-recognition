import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import EnrollmentConsentCopy from '../components/EnrollmentConsentCopy'
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
import { CURRENT_CONSENT_VERSION } from '../features/enrollment-capture/types'
import { humanizeReasons } from '../features/enrollment-management/reasonHumanizer'
import {
  canCancel,
  canGrantConsent,
  canRecapture,
  canResumeCapture,
  canRevoke,
} from '../features/enrollment-management/roleGating'
import StateBadge from '../features/enrollment-management/StateBadge'
import { getUser } from '../features/user-management/api'

/** How close to the bottom (px) counts as "scrolled to the end" — a few px
 * of slack absorbs sub-pixel rounding from browser zoom/scaling, so the
 * button isn't stuck disabled when the user has visibly reached the end. */
const SCROLL_BOTTOM_SLACK_PX = 4

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

  const [revokeConfirmText, setRevokeConfirmText] = useState('')
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)
  const [hasScrolledConsentToEnd, setHasScrolledConsentToEnd] = useState(false)
  const consentScrollRef = useRef<HTMLDivElement>(null)

  const detailQuery = useQuery({
    queryKey: ['enrollment', id],
    queryFn: () => getEnrollment(id as string),
    enabled: Boolean(id),
  })

  // Reset whenever the session changes (e.g. navigating from one
  // enrollment's detail page straight to another's, which React Router
  // does without unmounting this component) so a previous session's
  // scroll-read state can never carry over. A render-time adjustment (React's
  // own idiom for "reset state when a prop changes", see
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  // rather than an effect -- this is a synchronous derived reset, not a
  // side effect to synchronize with anything external.
  const [lastSeenId, setLastSeenId] = useState(id)
  if (id !== lastSeenId) {
    setLastSeenId(id)
    setHasScrolledConsentToEnd(false)
  }

  const consentSectionVisible = Boolean(
    detailQuery.data && canGrantConsent(detailQuery.data.state, role),
  )

  // A short consent text might not need scrolling at all (fits entirely in
  // the box already) -- treat that as "read" too, otherwise the button
  // would be stuck disabled forever with nothing to scroll. Runs after the
  // card (and therefore `consentScrollRef`'s node) actually exists in the
  // DOM, which `detailQuery`'s loading state gates.
  useEffect(() => {
    if (!consentSectionVisible) return
    const node = consentScrollRef.current
    if (node && node.scrollHeight <= node.clientHeight + SCROLL_BOTTOM_SLACK_PX) {
      setHasScrolledConsentToEnd(true)
    }
  }, [consentSectionVisible])

  const userQuery = useQuery({
    queryKey: ['user', detailQuery.data?.user_id],
    queryFn: () => getUser(detailQuery.data?.user_id as string),
    enabled: Boolean(detailQuery.data?.user_id),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['enrollment', id] })
    queryClient.invalidateQueries({ queryKey: ['enrollments'] })
  }

  const consentMutation = useMutation({
    mutationFn: () => grantConsent(id as string, CURRENT_CONSENT_VERSION),
    onSuccess: invalidate,
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
        title="Enrollment"
        description="ID sesi enrollment tidak valid."
      />
    )
  }

  if (detailQuery.isLoading) {
    return (
      <PagePlaceholder
        title="Detail Enrollment"
        description="Memuat data sesi enrollment..."
      />
    )
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <>
        <PagePlaceholder
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
  const showResumeCapture = canResumeCapture(session.state, role)
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
            <dt style={{ color: 'var(--text-secondary)' }}>Nama User</dt>
            <dd style={{ margin: 0 }}>
              {userQuery.data ? (
                <Link to={`/users/${session.user_id}`}>{userQuery.data.full_name}</Link>
              ) : (
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                  {session.user_id}
                </span>
              )}
            </dd>
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

      {(showConsent || showRecapture || showResumeCapture || showCancel || showRevoke) &&
        surfaceCard(
          <>
            <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Aksi</h2>

            {showConsent && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <p style={{ margin: 0, font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
                  Baca teks consent berikut (versi terbaru: <strong>{CURRENT_CONSENT_VERSION}</strong>)
                  sampai selesai sebelum mencatat persetujuan — tombol di bawah aktif setelah Anda
                  scroll sampai bagian akhir.
                </p>
                <div
                  ref={consentScrollRef}
                  onScroll={(event) => {
                    const el = event.currentTarget
                    if (el.scrollTop + el.clientHeight >= el.scrollHeight - SCROLL_BOTTOM_SLACK_PX) {
                      setHasScrolledConsentToEnd(true)
                    }
                  }}
                  style={{
                    maxHeight: 240,
                    overflowY: 'auto',
                    border: 'var(--border-w) solid var(--border-default)',
                    borderRadius: 'var(--radius-md)',
                    padding: 'var(--space-4)',
                    background: 'var(--bg-sunken)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 'var(--space-3)',
                  }}
                >
                  <EnrollmentConsentCopy />
                </div>
                <button
                  type="button"
                  disabled={!hasScrolledConsentToEnd || anyMutationPending}
                  onClick={() => consentMutation.mutate()}
                  style={{
                    alignSelf: 'flex-start',
                    minHeight: 'var(--touch-target)',
                    padding: '0 var(--space-5)',
                    borderRadius: 'var(--radius-md)',
                    border: 'var(--border-w) solid var(--accent)',
                    background: 'var(--accent)',
                    color: 'var(--text-inverse)',
                    cursor: hasScrolledConsentToEnd && !anyMutationPending ? 'pointer' : 'not-allowed',
                    opacity: hasScrolledConsentToEnd ? 1 : 0.5,
                  }}
                >
                  {consentMutation.isPending
                    ? 'Mencatat...'
                    : `Catat Consent (${CURRENT_CONSENT_VERSION})`}
                </button>
                {!hasScrolledConsentToEnd && (
                  <p style={{ margin: 0, font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
                    Scroll teks consent di atas sampai bawah untuk mengaktifkan tombol.
                  </p>
                )}
              </div>
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

            {showResumeCapture && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', alignItems: 'flex-start' }}>
                <button
                  type="button"
                  disabled={anyMutationPending}
                  onClick={() => navigate(`/enrollments/${id}/capture`)}
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
                  Lanjutkan / Coba Lagi Capture
                </button>
                <p style={{ margin: 0, font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
                  Sesi ini sedang dalam status "Sedang Capture" (mungkin sempat terputus). Klik
                  untuk membuka kembali halaman capture dan mencoba lagi.
                </p>
              </div>
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
