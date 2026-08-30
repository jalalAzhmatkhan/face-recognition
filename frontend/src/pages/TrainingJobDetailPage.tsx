import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import PagePlaceholder from './PagePlaceholder'
import {
  createTrainingJob,
  describeApiError,
  getTrainingJob,
  listModels,
} from '../features/training-models/api'
import { canAccessTrainingModels } from '../features/training-models/roleGating'
import { getCurrentRole } from '../lib/authToken'
import JobStatusBadge from '../features/training-models/JobStatusBadge'
import { IN_FLIGHT_JOB_STATUSES } from '../features/training-models/types'
import type { TrainingJobStatus } from '../features/training-models/types'
import '../features/training-models/TrainingModels.css'

const POLL_INTERVAL_MS = 4000

function isInFlight(status: TrainingJobStatus | undefined): boolean {
  return status === undefined || IN_FLIGHT_JOB_STATUSES.includes(status)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

function formatMetric(value: number | null): string {
  return value === null ? '—' : value.toFixed(4)
}

/**
 * S-51 Training Job Detail — FE-09 scope, ADMIN-only per screen-plan (see
 * `features/training-models/roleGating.ts`).
 *
 * Metric lookup note (documented per task instructions): `training_jobs`
 * itself never stores Recall/F1/Precision/latency — only `mlflow_run_id`
 * (see `backend/app/schemas/training.py::TrainingJobResponse`). Those
 * metrics live on the separate `models` table. So once a job is SUCCEEDED,
 * this page fetches `GET /models` and looks up the row whose `version`
 * matches the job's `model_version` to render the metric card.
 */
export default function TrainingJobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const role = getCurrentRole()
  const allowed = canAccessTrainingModels(role)
  const [retriedJobId, setRetriedJobId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const jobQuery = useQuery({
    queryKey: ['training-job', id],
    queryFn: () => getTrainingJob(id as string),
    enabled: allowed && Boolean(id),
    refetchInterval: (query) => (isInFlight(query.state.data?.status) ? POLL_INTERVAL_MS : false),
  })

  const job = jobQuery.data ?? null

  const modelsQuery = useQuery({
    queryKey: ['training-models', 'all'],
    queryFn: () => listModels(),
    enabled: allowed && job?.status === 'SUCCEEDED',
  })
  const resultModel =
    modelsQuery.data?.items.find((model) => model.version === job?.model_version) ?? null

  const retryMutation = useMutation({
    mutationFn: () =>
      createTrainingJob({
        model_version: job?.model_version ?? '',
        benchmark_id: job?.benchmark_id ?? '',
      }),
    onSuccess: (newJob) => {
      setRetriedJobId(newJob.id)
      void queryClient.invalidateQueries({ queryKey: ['training-jobs', 'list'] })
    },
  })

  if (!allowed) {
    return (
      <>
        <PagePlaceholder
          screenId="S-51"
          title="Training Job Detail"
          description="Detail status training job, metrik hasil, dan retry (FE-09)."
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

  return (
    <div className="training-models-page">
      <header className="training-models-page__header">
        <p className="mono training-models-page__screen-id">S-51</p>
        <h1>Training Job Detail</h1>
        <Link to="/models">&larr; Kembali ke Models &amp; Training</Link>
      </header>

      {jobQuery.isLoading && <p style={{ color: 'var(--text-secondary)' }}>Memuat data...</p>}
      {jobQuery.isError && (
        <p role="alert" style={{ color: 'var(--danger)' }}>
          {describeApiError(jobQuery.error)}
        </p>
      )}

      {job && (
        <>
          <section
            className={`training-models-job-header training-models-job-header--${job.status.toLowerCase()}`}
          >
            <JobStatusBadge status={job.status} />
            <dl className="training-models-job-header__meta">
              <div>
                <dt>Model Version</dt>
                <dd className="mono">{job.model_version ?? '—'}</dd>
              </div>
              <div>
                <dt>Benchmark ID</dt>
                <dd className="mono">{job.benchmark_id}</dd>
              </div>
              <div>
                <dt>Dipicu Pada</dt>
                <dd>{formatDate(job.created_at)}</dd>
              </div>
              <div>
                <dt>Selesai Pada</dt>
                <dd>{formatDate(job.completed_at)}</dd>
              </div>
              <div>
                <dt>MLflow Run ID</dt>
                <dd className="mono">
                  {job.mlflow_run_id ?? '—'}
                  {job.mlflow_run_id && (
                    <span className="training-models-job-header__mlflow-note">
                      {' '}
                      (teks saja — belum ada konfigurasi base URL MLflow di frontend)
                    </span>
                  )}
                </dd>
              </div>
            </dl>
          </section>

          {job.status === 'SUCCEEDED' && (
            <section className="training-models-section">
              <h2 className="training-models-section__title">Metrik Hasil Training</h2>
              {modelsQuery.isLoading && <p>Memuat metrik...</p>}
              {modelsQuery.isError && (
                <p role="alert" style={{ color: 'var(--danger)' }}>
                  {describeApiError(modelsQuery.error)}
                </p>
              )}
              {resultModel ? (
                <dl className="training-models-metrics-hierarchy">
                  <div className="training-models-metrics-hierarchy__primary">
                    <dt>Recall</dt>
                    <dd>{formatMetric(resultModel.recall)}</dd>
                  </div>
                  <div>
                    <dt>F1</dt>
                    <dd>{formatMetric(resultModel.f1)}</dd>
                  </div>
                  <div>
                    <dt>Precision</dt>
                    <dd>{formatMetric(resultModel.precision)}</dd>
                  </div>
                  <div>
                    <dt>Latency p95</dt>
                    <dd>
                      {resultModel.latency_ms_p95 === null
                        ? '—'
                        : `${resultModel.latency_ms_p95} ms`}
                    </dd>
                  </div>
                  {resultModel.stage === 'CANDIDATE' && (
                    <div>
                      <Link to={`/models/${encodeURIComponent(resultModel.version)}/promote`}>
                        Review untuk promosi &rarr;
                      </Link>
                    </div>
                  )}
                </dl>
              ) : (
                !modelsQuery.isLoading && (
                  <p style={{ color: 'var(--text-secondary)' }}>
                    Job selesai tapi belum ditemukan model versi &quot;{job.model_version}&quot; di{' '}
                    <code>GET /models</code>.
                  </p>
                )
              )}
            </section>
          )}

          {job.status === 'FAILED' && (
            <section className="training-models-section">
              <h2 className="training-models-section__title">Job Gagal</h2>
              <p role="alert" style={{ color: 'var(--danger)' }}>
                {job.error_message ?? 'Tidak ada pesan error dari server.'}
              </p>
              <details className="training-models-log-tail">
                <summary>Log tail</summary>
                <pre>{job.error_message ?? '(tidak ada log tersedia)'}</pre>
              </details>
              <button
                type="button"
                disabled={retryMutation.isPending}
                onClick={() => retryMutation.mutate()}
              >
                {retryMutation.isPending ? 'Memulai job baru...' : 'Coba lagi (job baru)'}
              </button>
              <p className="training-models-section__hint">
                Ini memicu job training BARU dengan model_version/benchmark_id yang sama — BUKAN
                retry job ini (backend tidak punya endpoint retry sungguhan).
              </p>
              {retryMutation.isError && (
                <p role="alert" style={{ color: 'var(--danger)' }}>
                  {describeApiError(retryMutation.error)}
                </p>
              )}
              {retriedJobId && (
                <p>
                  Job baru dibuat: <Link to={`/models/jobs/${retriedJobId}`}>{retriedJobId}</Link>
                </p>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
