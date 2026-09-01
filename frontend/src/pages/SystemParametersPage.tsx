import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import { describeApiError, getEnrollmentQualityParams, updateEnrollmentQualityParams } from '../features/system-parameters/api'
import { canAccessSystemParameters } from '../features/system-parameters/roleGating'
import { getCurrentRole } from '../lib/authToken'

/** "System Parameter" admin menu — currently exposes exactly one
 * parameter: the Enrollment capture wizard's sharpness/brightness gate.
 * ADMIN-only (see `features/system-parameters/roleGating.ts`).
 *
 * Both the frontend live preflight (`enrollment-capture/EnrollmentCapturePage.tsx`)
 * and ai-training's server-side QC gate (`ai_training.quality.pipeline.
 * resolve_qc_settings`) resolve against the SAME `enrollment_capture_quality`
 * value this page writes — saving here changes what both surfaces enforce,
 * without a redeploy.
 */
export default function SystemParametersPage() {
  const role = getCurrentRole()
  const allowed = canAccessSystemParameters(role)
  const queryClient = useQueryClient()

  const [minBlurVariance, setMinBlurVariance] = useState('')
  const [minBrightness, setMinBrightness] = useState('')
  const [maxBrightness, setMaxBrightness] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const paramsQuery = useQuery({
    queryKey: ['system-parameters', 'enrollment-quality'],
    queryFn: getEnrollmentQualityParams,
    enabled: allowed,
  })

  // Populate the form fields exactly once, the first time the current
  // effective values load — a render-time adjustment (React's own idiom
  // for "adjust state when a prop changes") rather than an effect. Only
  // the initial load populates the form; a save's own submitted values
  // already reflect what the form shows, so there's nothing to re-sync
  // after `saveMutation` succeeds.
  const [initializedFromQuery, setInitializedFromQuery] = useState(false)
  if (paramsQuery.data && !initializedFromQuery) {
    setInitializedFromQuery(true)
    setMinBlurVariance(String(paramsQuery.data.min_blur_variance))
    setMinBrightness(String(paramsQuery.data.min_brightness))
    setMaxBrightness(String(paramsQuery.data.max_brightness))
  }

  const saveMutation = useMutation({
    mutationFn: updateEnrollmentQualityParams,
    onSuccess: (data) => {
      setSaved(true)
      queryClient.setQueryData(['system-parameters', 'enrollment-quality'], data)
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          title="System Parameter"
          description="Konfigurasi parameter operasional sistem."
        />
        <div
          role="alert"
          style={{
            marginTop: 'var(--space-6)',
            background: 'var(--bg-surface)',
            border: 'var(--border-w) solid var(--border-default)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-sm)',
            padding: 'var(--space-8)',
            color: 'var(--text-secondary)',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-2)',
          }}
        >
          <h2 style={{ margin: 0, font: 'var(--text-h3)', color: 'var(--text-primary)' }}>
            Tidak Ada Akses
          </h2>
          <p style={{ margin: 0 }}>
            Halaman ini hanya dapat diakses oleh role ADMIN. Role kamu saat ini
            {role ? ` (${role})` : ''} tidak memiliki izin untuk melihat data ini.
          </p>
        </div>
      </>
    )
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setSaved(false)
    setValidationError(null)

    const parsedMinBlur = Number(minBlurVariance)
    const parsedMinBrightness = Number(minBrightness)
    const parsedMaxBrightness = Number(maxBrightness)

    if (
      !Number.isFinite(parsedMinBlur) ||
      !Number.isFinite(parsedMinBrightness) ||
      !Number.isFinite(parsedMaxBrightness)
    ) {
      setValidationError('Semua nilai harus berupa angka.')
      return
    }
    if (parsedMinBlur <= 0) {
      setValidationError('Min. Ketajaman (Blur Variance) harus lebih besar dari 0.')
      return
    }
    if (parsedMinBrightness < 0 || parsedMinBrightness > 255) {
      setValidationError('Min. Kecerahan harus di antara 0 dan 255.')
      return
    }
    if (parsedMaxBrightness < 0 || parsedMaxBrightness > 255) {
      setValidationError('Maks. Kecerahan harus di antara 0 dan 255.')
      return
    }
    if (parsedMinBrightness >= parsedMaxBrightness) {
      setValidationError('Min. Kecerahan harus lebih kecil dari Maks. Kecerahan.')
      return
    }

    saveMutation.mutate({
      min_blur_variance: parsedMinBlur,
      min_brightness: parsedMinBrightness,
      max_brightness: parsedMaxBrightness,
    })
  }

  return (
    <>
      <PagePlaceholder
        title="System Parameter"
        description="Konfigurasi parameter operasional sistem."
      />

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
          maxWidth: 560,
        }}
      >
        <div>
          <h2 style={{ margin: 0, font: 'var(--text-h3)' }}>Kualitas Capture Enrollment</h2>
          <p style={{ margin: 'var(--space-2) 0 0', color: 'var(--text-secondary)' }}>
            Ambang batas ketajaman (sharpness) dan pencahayaan (lighting) untuk proses capture
            di menu Enrollment — berlaku untuk pratinjau langsung di wizard capture MAUPUN
            pemeriksaan kualitas (QC) di server setelah video diunggah. Longgarkan Min. Ketajaman
            bila banyak user melakukan enrollment memakai kamera bawaan laptop (biasanya kurang
            tajam dibanding kamera eksternal).
          </p>
        </div>

        {paramsQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {paramsQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(paramsQuery.error)}
          </p>
        )}

        {paramsQuery.data && (
          <form
            onSubmit={handleSubmit}
            style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}
          >
            {paramsQuery.data.is_default && (
              <p style={{ margin: 0, font: 'var(--text-small)', color: 'var(--text-muted)' }}>
                Belum pernah disimpan — nilai di bawah adalah default bawaan sistem.
              </p>
            )}

            <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              <span>Min. Ketajaman (Blur Variance)</span>
              <input
                type="number"
                step="any"
                value={minBlurVariance}
                onChange={(event) => setMinBlurVariance(event.target.value)}
                style={{
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--border-default)',
                }}
              />
              <span style={{ font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
                Semakin kecil nilainya, semakin longgar (menerima gambar kurang tajam).
              </span>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              <span>Min. Kecerahan (0-255)</span>
              <input
                type="number"
                step="any"
                value={minBrightness}
                onChange={(event) => setMinBrightness(event.target.value)}
                style={{
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--border-default)',
                }}
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              <span>Maks. Kecerahan (0-255)</span>
              <input
                type="number"
                step="any"
                value={maxBrightness}
                onChange={(event) => setMaxBrightness(event.target.value)}
                style={{
                  minHeight: 'var(--touch-target)',
                  padding: '0 var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--border-default)',
                }}
              />
            </label>

            {validationError && (
              <p role="alert" style={{ margin: 0, color: 'var(--danger)' }}>
                {validationError}
              </p>
            )}
            {saveMutation.isError && (
              <p role="alert" style={{ margin: 0, color: 'var(--danger)' }}>
                {describeApiError(saveMutation.error)}
              </p>
            )}
            {saved && !saveMutation.isPending && (
              <p style={{ margin: 0, color: 'var(--success)' }}>Parameter berhasil disimpan.</p>
            )}

            <button
              type="submit"
              disabled={saveMutation.isPending}
              style={{
                alignSelf: 'flex-start',
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: saveMutation.isPending ? 'not-allowed' : 'pointer',
                opacity: saveMutation.isPending ? 0.5 : 1,
              }}
            >
              {saveMutation.isPending ? 'Menyimpan...' : 'Simpan'}
            </button>
          </form>
        )}
      </section>
    </>
  )
}
