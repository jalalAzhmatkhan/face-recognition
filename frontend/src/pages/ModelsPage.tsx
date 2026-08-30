import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import { createTrainingJob, describeApiError, listModels } from '../features/training-models/api'
import { canAccessTrainingModels } from '../features/training-models/roleGating'
import { getCurrentRole } from '../lib/authToken'
import ProductionModelCard from '../features/training-models/ProductionModelCard'
import ModelsTable from '../features/training-models/ModelsTable'
import SessionJobsTable from '../features/training-models/SessionJobsTable'
import StartTrainingDialog from '../features/training-models/StartTrainingDialog'
import {
  addSessionTrainingJob,
  listSessionTrainingJobs,
} from '../features/training-models/sessionJobs'
import '../features/training-models/TrainingModels.css'

/**
 * S-50 Models & Training — FE-09 scope. ADMIN-only per screen-plan (see
 * `features/training-models/roleGating.ts` docstring for why this is
 * stricter than the backend's technical read ceiling).
 *
 * The "tabel training runs" here is a browser-session-local list, NOT a
 * server-side history — see `features/training-models/sessionJobs.ts` for
 * why (BE-13 has no `GET /training/jobs` list endpoint; candidate follow-up
 * task "BE-15: GET /training/jobs list endpoint").
 */
export default function ModelsPage() {
  const role = getCurrentRole()
  const allowed = canAccessTrainingModels(role)
  const queryClient = useQueryClient()

  const [showStartDialog, setShowStartDialog] = useState(false)
  const [sessionJobs, setSessionJobs] = useState(() => listSessionTrainingJobs())

  const modelsQuery = useQuery({
    queryKey: ['training-models', 'all'],
    queryFn: () => listModels(),
    enabled: allowed,
  })

  const startMutation = useMutation({
    mutationFn: createTrainingJob,
    onSuccess: (job) => {
      addSessionTrainingJob({
        id: job.id,
        model_version: job.model_version ?? '',
        benchmark_id: job.benchmark_id,
        created_at: job.created_at,
      })
      setSessionJobs(listSessionTrainingJobs())
      setShowStartDialog(false)
      void queryClient.invalidateQueries({ queryKey: ['training-job', job.id] })
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          screenId="S-50"
          title="Models & Training"
          description="Daftar model + metrik (Recall/F1/Precision/latency ms), training jobs, dan promotion review (FE-09)."
        />
        <div className="training-models-denied" role="alert">
          <h2 className="training-models-denied__title">Tidak Ada Akses</h2>
          <p style={{ margin: 0 }}>
            Halaman ini hanya dapat diakses oleh role ADMIN. Role kamu saat ini
            {role ? ` (${role})` : ''} tidak memiliki izin untuk melihat data model/training.
          </p>
        </div>
      </>
    )
  }

  const items = modelsQuery.data?.items ?? []
  const production = items.find((model) => model.stage === 'PRODUCTION') ?? null

  return (
    <div className="training-models-page">
      <header className="training-models-page__header">
        <p className="mono training-models-page__screen-id">S-50</p>
        <h1>Models & Training</h1>
      </header>

      <ProductionModelCard model={production} />

      <section className="training-models-section">
        <h2 className="training-models-section__title">Semua Model</h2>
        {modelsQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {modelsQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(modelsQuery.error)}
          </p>
        )}
        {!modelsQuery.isLoading && !modelsQuery.isError && <ModelsTable models={items} />}
      </section>

      <section className="training-models-section">
        <div className="training-models-section__header">
          <h2 className="training-models-section__title">Job Training (dipicu di sesi ini)</h2>
          <button type="button" onClick={() => setShowStartDialog(true)}>
            Mulai Training
          </button>
        </div>
        <p className="training-models-section__hint">
          Daftar ini HANYA berisi job yang dipicu dari browser ini (tersimpan di localStorage) —
          BUKAN riwayat lengkap dari server, karena backend belum menyediakan endpoint daftar
          training job (lihat catatan gap FE-09 / calon BE-15).
        </p>
        <SessionJobsTable jobs={sessionJobs} />
      </section>

      {showStartDialog && (
        <StartTrainingDialog
          isSubmitting={startMutation.isPending}
          errorMessage={startMutation.isError ? describeApiError(startMutation.error) : null}
          onSubmit={(values) => startMutation.mutate(values)}
          onCancel={() => setShowStartDialog(false)}
        />
      )}
    </div>
  )
}
