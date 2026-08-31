import type { ModelVersionResponse } from './types'

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

/** Dashboard's compact "Model produksi" panel (screen-plan S-02, baris 2).
 * Deliberately its own small component rather than reusing
 * `training-models/ProductionModelCard.tsx` (per this project's per-feature
 * duplication convention) — same fields, honest empty state when there is
 * no production model yet (never fabricate one). */
export default function ProductionModelPanel({
  model,
  isLoading,
}: {
  model: ModelVersionResponse | null
  isLoading: boolean
}) {
  if (isLoading) {
    return <div className="dashboard-panel dashboard-panel--skeleton" aria-busy="true" />
  }

  if (!model) {
    return (
      <section className="dashboard-panel" aria-label="Model produksi">
        <h3 className="dashboard-panel__title">Model Produksi</h3>
        <p className="dashboard-panel__empty-hint">
          Belum ada model produksi — sistem memakai model pretrained bawaan.
        </p>
      </section>
    )
  }

  return (
    <section className="dashboard-panel" aria-label="Model produksi">
      <h3 className="dashboard-panel__title">Model Produksi</h3>
      <p className="dashboard-panel__version mono">{model.version}</p>
      <dl className="dashboard-panel__metrics">
        <div>
          <dt>Recall</dt>
          <dd>{formatMetric(model.recall)}</dd>
        </div>
        <div>
          <dt>F1</dt>
          <dd>{formatMetric(model.f1)}</dd>
        </div>
        <div>
          <dt>Precision</dt>
          <dd>{formatMetric(model.precision)}</dd>
        </div>
      </dl>
      <p className="dashboard-panel__hint">
        Dipromosikan pada {formatDate(model.promoted_at)}
      </p>
    </section>
  )
}
