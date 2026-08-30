import { Link } from 'react-router-dom'
import type { ModelVersionResponse } from './types'
import StageBadge from './StageBadge'

function formatMetric(value: number | null): string {
  return value === null ? '—' : value.toFixed(4)
}

/** S-50 middle table: every model (no stage filter). "Review" only appears
 * for CANDIDATE rows (screen-plan: "aksi 'Review' bila CANDIDATE -> S-52") —
 * PRODUCTION/RETIRED rows have nothing to review/promote. */
export default function ModelsTable({ models }: { models: ModelVersionResponse[] }) {
  if (models.length === 0) {
    return (
      <div className="training-models-empty">
        <h3 className="training-models-empty__title">Belum Ada Model</h3>
        <p className="training-models-empty__hint">
          Belum ada model — sistem memakai model pretrained bawaan.
        </p>
      </div>
    )
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="training-models-table">
        <thead>
          <tr>
            <th>Versi</th>
            <th>Stage</th>
            <th>Recall</th>
            <th>F1</th>
            <th>Precision</th>
            <th>Latency p95</th>
            <th>Dipromosikan</th>
            <th>Aksi</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={model.version}>
              <td className="mono">{model.version}</td>
              <td>
                <StageBadge stage={model.stage} />
              </td>
              <td>{formatMetric(model.recall)}</td>
              <td>{formatMetric(model.f1)}</td>
              <td>{formatMetric(model.precision)}</td>
              <td>{model.latency_ms_p95 === null ? '—' : `${model.latency_ms_p95} ms`}</td>
              <td>
                {model.promoted_at ? new Date(model.promoted_at).toLocaleDateString('id-ID') : '—'}
              </td>
              <td>
                {model.stage === 'CANDIDATE' && (
                  <Link to={`/models/${encodeURIComponent(model.version)}/promote`}>Review</Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
