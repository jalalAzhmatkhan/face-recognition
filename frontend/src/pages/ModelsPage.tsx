import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  createTrainingJob,
  describeApiError,
  listModels,
  listTrainingJobs,
} from '../features/training-models/api'
import { canAccessTrainingModels } from '../features/training-models/roleGating'
import { getCurrentRole } from '../lib/authToken'
import ProductionModelCard from '../features/training-models/ProductionModelCard'
import ModelsTable from '../features/training-models/ModelsTable'
import TrainingJobsTable from '../features/training-models/TrainingJobsTable'
import StartTrainingDialog from '../features/training-models/StartTrainingDialog'
import { IN_FLIGHT_JOB_STATUSES } from '../features/training-models/types'
import '../features/training-models/TrainingModels.css'

const JOBS_POLL_INTERVAL_MS = 4000

/**
 * S-50 Models & Training — FE-09 scope. ADMIN-only per screen-plan (see
 * `features/training-models/roleGating.ts` docstring for why this is
 * stricter than the backend's technical read ceiling).
 *
 * The "tabel training runs" is real server-side history via `GET
 * /training/jobs` (BE-15) — this used to be a browser-localStorage-only
 * workaround before that endpoint existed.
 */
export default function ModelsPage() {
  const role = getCurrentRole()
  const allowed = canAccessTrainingModels(role)
  const queryClient = useQueryClient()

  const [showStartDialog, setShowStartDialog] = useState(false)

  const modelsQuery = useQuery({
    queryKey: ['training-models', 'all'],
    queryFn: () => listModels(),
    enabled: allowed,
  })

  const jobsQuery = useQuery({
    queryKey: ['training-jobs', 'list'],
    queryFn: () => listTrainingJobs({ limit: 20 }),
    enabled: allowed,
    // Keep polling while any of the visible jobs is still PENDING/RUNNING,
    // same "stop once settled" spirit as the per-job polling on S-51.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const anyInFlight = items.some((job) => IN_FLIGHT_JOB_STATUSES.includes(job.status))
      return anyInFlight ? JOBS_POLL_INTERVAL_MS : false
    },
  })

  const startMutation = useMutation({
    mutationFn: createTrainingJob,
    onSuccess: () => {
      setShowStartDialog(false)
      void queryClient.invalidateQueries({ queryKey: ['training-jobs', 'list'] })
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          title="Models & Training"
          description="Daftar model + metrik (Recall/F1/Precision/latency ms), training jobs, dan promotion review."
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
          <h2 className="training-models-section__title">Riwayat Training</h2>
          <button type="button" onClick={() => setShowStartDialog(true)}>
            Mulai Training
          </button>
        </div>
        {jobsQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
        {jobsQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(jobsQuery.error)}
          </p>
        )}
        {!jobsQuery.isLoading && !jobsQuery.isError && (
          <TrainingJobsTable jobs={jobsQuery.data?.items ?? []} />
        )}
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
