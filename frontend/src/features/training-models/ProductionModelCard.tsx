import type { ModelVersionResponse } from './types'
import StageBadge from './StageBadge'

function formatMetric(value: number | null): string {
  return value === null ? '—' : value.toFixed(4)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('id-ID')
  } catch {
    return iso
  }
}

/** S-50 top card: current PRODUCTION model (there should be 0 or 1 —
 * `promote_model` retires any previous production model on every promotion,
 * so `models` never has two PRODUCTION rows at once). Honest empty state
 * when there is none, per task instructions — never invent a production
 * model. */
export default function ProductionModelCard({ model }: { model: ModelVersionResponse | null }) {
  if (!model) {
    return (
      <section className="training-models-card training-models-card--empty">
        <h2 className="training-models-card__title">Model Produksi</h2>
        <p className="training-models-card__empty-hint">
          Belum ada model produksi — sistem memakai model pretrained bawaan.
        </p>
      </section>
    )
  }

  return (
    <section className="training-models-card">
      <div className="training-models-card__header">
        <h2 className="training-models-card__title">Model Produksi</h2>
        <StageBadge stage={model.stage} />
      </div>
      <p className="training-models-card__version mono">{model.version}</p>
      <p className="training-models-card__recall">
        <span className="training-models-card__recall-value">{formatMetric(model.recall)}</span>
        <span className="training-models-card__recall-label">Recall</span>
      </p>
      <dl className="training-models-card__metrics">
        <div>
          <dt>F1</dt>
          <dd>{formatMetric(model.f1)}</dd>
        </div>
        <div>
          <dt>Precision</dt>
          <dd>{formatMetric(model.precision)}</dd>
        </div>
        <div>
          <dt>Latency p95</dt>
          <dd>{model.latency_ms_p95 === null ? '—' : `${model.latency_ms_p95} ms`}</dd>
        </div>
      </dl>
      <p className="training-models-card__promoted">
        Dipromosikan oleh {model.promoted_by ?? '—'} pada {formatDate(model.promoted_at)}
      </p>
    </section>
  )
}
