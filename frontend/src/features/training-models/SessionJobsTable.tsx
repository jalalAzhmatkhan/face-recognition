import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { SessionTrainingJob, TrainingJobStatus } from './types'
import { IN_FLIGHT_JOB_STATUSES } from './types'
import { getTrainingJob } from './api'
import JobStatusBadge from './JobStatusBadge'

const POLL_INTERVAL_MS = 4000

function isInFlight(status: TrainingJobStatus | undefined): boolean {
  return status === undefined || IN_FLIGHT_JOB_STATUSES.includes(status)
}

function SessionJobRow({ job }: { job: SessionTrainingJob }) {
  const jobQuery = useQuery({
    queryKey: ['training-job', job.id],
    queryFn: () => getTrainingJob(job.id),
    // Stops polling the instant the job reaches SUCCEEDED/FAILED (S-50 task
    // instructions) instead of polling forever.
    refetchInterval: (query) => (isInFlight(query.state.data?.status) ? POLL_INTERVAL_MS : false),
  })

  return (
    <tr>
      <td className="mono">{job.model_version}</td>
      <td className="mono">{job.benchmark_id}</td>
      <td>{new Date(job.created_at).toLocaleString('id-ID')}</td>
      <td>
        {jobQuery.isLoading && 'Memuat...'}
        {jobQuery.isError && <span style={{ color: 'var(--danger)' }}>Gagal memuat status</span>}
        {jobQuery.data && <JobStatusBadge status={jobQuery.data.status} />}
      </td>
      <td>
        <Link to={`/models/jobs/${job.id}`}>Detail</Link>
      </td>
    </tr>
  )
}

/**
 * S-50 "tabel training runs" — see `sessionJobs.ts` for why this lists
 * browser-session-local jobs (localStorage) instead of a server-side
 * history: BE-13 has no `GET /training/jobs` list endpoint (GAP #1).
 */
export default function SessionJobsTable({ jobs }: { jobs: SessionTrainingJob[] }) {
  if (jobs.length === 0) {
    return (
      <p className="training-models-empty__hint">
        Belum ada job training yang dipicu di sesi browser ini.
      </p>
    )
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="training-models-table">
        <thead>
          <tr>
            <th>Model Version</th>
            <th>Benchmark ID</th>
            <th>Dipicu Pada</th>
            <th>Status</th>
            <th>Aksi</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <SessionJobRow key={job.id} job={job} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
