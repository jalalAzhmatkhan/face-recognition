import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  describeApiError,
  listModels,
  promoteModel,
  promotionGateReasons,
} from '../features/training-models/api'
import { canAccessTrainingModels } from '../features/training-models/roleGating'
import { getCurrentRole } from '../lib/authToken'
import {
  compareHigherIsBetter,
  compareLowerIsBetter,
  computePromotionGateChecks,
  type MetricDirection,
} from '../features/training-models/gateChecks'
import GateChecklist from '../features/training-models/GateChecklist'
import PromoteConfirmDialog from '../features/training-models/PromoteConfirmDialog'
import '../features/training-models/TrainingModels.css'

function formatMetric(value: number | null): string {
  return value === null ? '—' : value.toFixed(4)
}

function deltaArrow(direction: MetricDirection): string {
  if (direction === 'up') return '▲'
  if (direction === 'down') return '▼'
  if (direction === 'flat') return '='
  return '—'
}

function deltaColor(direction: MetricDirection): string {
  if (direction === 'up') return 'var(--success)'
  if (direction === 'down') return 'var(--danger)'
  return 'var(--text-secondary)'
}

/**
 * S-52 Promotion Review — FE-09 scope, ADMIN-only per screen-plan (see
 * `features/training-models/roleGating.ts`).
 *
 * "Tolak kandidat" is a SESSION-LOCAL dismiss only (GAP #2, documented per
 * task instructions): `ModelStage` on the backend is only
 * CANDIDATE/PRODUCTION/RETIRED — there is no REJECTED stage and no reject
 * endpoint at all. This mirrors FE-06's "tandai ditinjau" pattern
 * (`live-monitoring/SpoofBanner.tsx` / `LiveMonitoringPage.tsx`): hiding the
 * candidate from view here does not call any API and does not change
 * anything on the server.
 */
export default function ModelPromotionPage() {
  const { version } = useParams<{ version: string }>()
  const queryClient = useQueryClient()
  const role = getCurrentRole()
  const allowed = canAccessTrainingModels(role)

  const [dismissed, setDismissed] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [promoteSuccess, setPromoteSuccess] = useState(false)
  const [serverReasons, setServerReasons] = useState<string[] | null>(null)

  const modelsQuery = useQuery({
    queryKey: ['training-models', 'all'],
    queryFn: () => listModels(),
    enabled: allowed,
  })

  const promoteMutation = useMutation({
    mutationFn: () => promoteModel(version as string, { confirm: true }),
    onSuccess: () => {
      setShowConfirm(false)
      setPromoteSuccess(true)
      setServerReasons(null)
      void queryClient.invalidateQueries({ queryKey: ['training-models'] })
    },
    onError: (error) => {
      setServerReasons(promotionGateReasons(error))
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          screenId="S-52"
          title="Promotion Review"
          description="Review dan promosi model kandidat ke produksi (FE-09)."
        />
        <div className="training-models-denied" role="alert">
          <h2 className="training-models-denied__title">Tidak Ada Akses</h2>
          <p style={{ margin: 0 }}>
            Halaman ini hanya dapat diakses oleh role ADMIN. Role kamu saat ini
            {role ? ` (${role})` : ''} tidak memiliki izin untuk melihat data ini.
          </p>
        </div>
      </>
    )
  }

  const items = modelsQuery.data?.items ?? []
  const candidate = items.find((model) => model.version === version) ?? null
  const production = items.find((model) => model.stage === 'PRODUCTION') ?? null

  return (
    <div className="training-models-page">
      <header className="training-models-page__header">
        <p className="mono training-models-page__screen-id">S-52</p>
        <h1>Promotion Review</h1>
        <Link to="/models">&larr; Kembali ke Models &amp; Training</Link>
      </header>

      {modelsQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
      {modelsQuery.isError && (
        <p role="alert" style={{ color: 'var(--danger)' }}>
          {describeApiError(modelsQuery.error)}
        </p>
      )}

      {!modelsQuery.isLoading && !modelsQuery.isError && !candidate && (
        <p role="alert" style={{ color: 'var(--danger)' }}>
          Model versi &quot;{version}&quot; tidak ditemukan di <code>GET /models</code>.
        </p>
      )}

      {promoteSuccess && (
        <div className="training-models-success-banner" role="status">
          <strong>Promosi berhasil.</strong> Versi {version} sekarang PRODUCTION.
          <p style={{ margin: '4px 0 0' }}>
            Catatan: re-embedding gallery belum otomatis — TR-08 belum diimplementasikan, perlu
            tindakan manual terpisah agar gallery memakai model baru (FR-TRN-06).
          </p>
        </div>
      )}

      {candidate && !dismissed && !promoteSuccess && (
        <>
          <section className="training-models-section">
            <h2 className="training-models-section__title">Kandidat vs Produksi</h2>
            {!production && (
              <p className="training-models-section__hint">Belum ada baseline produksi.</p>
            )}
            <div style={{ overflowX: 'auto' }}>
              <table className="training-models-table">
                <thead>
                  <tr>
                    <th>Metrik</th>
                    <th>Kandidat ({candidate.version})</th>
                    <th>Produksi{production ? ` (${production.version})` : ''}</th>
                    <th>Delta</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ['Recall', candidate.recall, production?.recall ?? null],
                      ['F1', candidate.f1, production?.f1 ?? null],
                      ['Precision', candidate.precision, production?.precision ?? null],
                    ] as const
                  ).map(([label, candidateVal, productionVal]) => {
                    const delta = compareHigherIsBetter(candidateVal, productionVal)
                    return (
                      <tr key={label}>
                        <td>{label}</td>
                        <td>{formatMetric(candidateVal)}</td>
                        <td>{production ? formatMetric(productionVal) : '—'}</td>
                        <td style={{ color: deltaColor(production ? delta.direction : 'unknown') }}>
                          {production ? deltaArrow(delta.direction) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                  <tr>
                    <td>Latency p95</td>
                    <td>
                      {candidate.latency_ms_p95 === null ? '—' : `${candidate.latency_ms_p95} ms`}
                    </td>
                    <td>
                      {production
                        ? production.latency_ms_p95 === null
                          ? '—'
                          : `${production.latency_ms_p95} ms`
                        : '—'}
                    </td>
                    {(() => {
                      const delta = compareLowerIsBetter(
                        candidate.latency_ms_p95,
                        production?.latency_ms_p95 ?? null,
                      )
                      return (
                        <td style={{ color: deltaColor(production ? delta.direction : 'unknown') }}>
                          {production ? deltaArrow(delta.direction) : '—'}
                        </td>
                      )
                    })()}
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="training-models-section">
            <h2 className="training-models-section__title">Checklist Gate Promosi</h2>
            <GateChecklist checks={computePromotionGateChecks(candidate, production)} />

            {serverReasons && (
              <div role="alert" className="training-models-server-reasons">
                <strong>Server menolak promosi:</strong>
                <ul>
                  {serverReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            )}
            {promoteMutation.isError && !serverReasons && (
              <p role="alert" style={{ color: 'var(--danger)' }}>
                {describeApiError(promoteMutation.error)}
              </p>
            )}

            <div className="training-models-dialog__actions">
              <button
                type="button"
                disabled={!computePromotionGateChecks(candidate, production).allPassed}
                onClick={() => setShowConfirm(true)}
              >
                Promote ke Produksi
              </button>
              <button type="button" onClick={() => setDismissed(true)}>
                Tolak Kandidat
              </button>
            </div>
          </section>
        </>
      )}

      {dismissed && !promoteSuccess && (
        <p className="training-models-section__hint">
          Kandidat {version} disembunyikan untuk sesi ini saja — TIDAK mengubah status apapun di
          server (backend tidak punya stage REJECTED, lihat catatan gap FE-09).{' '}
          <button type="button" onClick={() => setDismissed(false)}>
            Tampilkan lagi
          </button>
        </p>
      )}

      {showConfirm && candidate && (
        <PromoteConfirmDialog
          candidateVersion={candidate.version}
          productionVersion={production?.version ?? null}
          isSubmitting={promoteMutation.isPending}
          onConfirm={() => promoteMutation.mutate()}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  )
}
