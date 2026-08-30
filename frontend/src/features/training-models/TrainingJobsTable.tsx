import { Link } from 'react-router-dom'
import type { TrainingJobResponse } from './types'
import JobStatusBadge from './JobStatusBadge'

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

/**
 * S-50 "tabel training runs" — real server-side history via `GET
 * /training/jobs` (BE-15). Each row already carries its own `status`
 * (returned by the list endpoint itself), so unlike the earlier
 * localStorage-based version this table needs no per-row polling — the
 * parent page's list query re-fetches on an interval while any job is
 * still in flight (see `ModelsPage.tsx`).
 */
export default function TrainingJobsTable({ jobs }: { jobs: TrainingJobResponse[] }) {
  if (jobs.length === 0) {
    return (
      <p className="training-models-empty__hint">Belum ada job training yang pernah dijalankan.</p>
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
            <tr key={job.id}>
              <td className="mono">{job.model_version ?? '—'}</td>
              <td className="mono">{job.benchmark_id}</td>
              <td>{formatDate(job.created_at)}</td>
              <td>
                <JobStatusBadge status={job.status} />
              </td>
              <td>
                <Link to={`/models/jobs/${job.id}`}>Detail</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
