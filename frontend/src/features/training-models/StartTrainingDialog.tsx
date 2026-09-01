import { useState } from 'react'

export interface StartTrainingValues {
  model_version: string
  benchmark_id: string
}

interface StartTrainingDialogProps {
  isSubmitting: boolean
  errorMessage: string | null
  onSubmit: (values: StartTrainingValues) => void
  onCancel: () => void
}

/**
 * S-50 "Mulai Training" dialog — SIMPLIFIED per FE-09 task instructions
 * (GAP #3): screen-plan calls for a "dialog: dataset filter", but there is
 * no backend endpoint to create or list dataset snapshots at all
 * (`ai-training snapshot` is CLI-only, TR-04 — see
 * `documentation/tsd` for that pipeline). This is therefore a plain
 * two-field form where the operator types a `model_version` label and an
 * existing `benchmark_id` (snapshot id) they already know from the CLI or
 * documentation — NOT a dropdown/browser over real datasets.
 *
 * The explicit confirmation checkbox (not just filled text fields) mirrors
 * `PromoteConfirmDialog`'s pattern: `POST /training/jobs` kicks off a real
 * GPU training run, so submission should require a deliberate acknowledge
 * step, not just typing into two inputs and hitting Enter.
 */
export default function StartTrainingDialog({
  isSubmitting,
  errorMessage,
  onSubmit,
  onCancel,
}: StartTrainingDialogProps) {
  const [modelVersion, setModelVersion] = useState('')
  const [benchmarkId, setBenchmarkId] = useState('')
  const [confirmed, setConfirmed] = useState(false)

  const canSubmit = modelVersion.trim() !== '' && benchmarkId.trim() !== '' && confirmed

  return (
    <div role="presentation" className="training-models-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-training-title"
        className="training-models-dialog"
      >
        <h2 id="start-training-title" className="training-models-dialog__title">
          Mulai Training Baru
        </h2>
        <p className="training-models-dialog__hint">
          Dataset snapshot dipilih lewat ID yang sudah kamu siapkan (CLI{' '}
          <code>ai-training snapshot</code> / dokumentasi) — belum ada browser/filter dataset di UI
          ini.
        </p>

        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (canSubmit) {
              onSubmit({ model_version: modelVersion.trim(), benchmark_id: benchmarkId.trim() })
            }
          }}
          className="training-models-dialog__form"
        >
          <label htmlFor="training-model-version">Model Version</label>
          <input
            id="training-model-version"
            value={modelVersion}
            onChange={(event) => setModelVersion(event.target.value)}
            placeholder="mis. facenet-v3"
          />

          <label htmlFor="training-benchmark-id">Benchmark / Dataset Snapshot ID</label>
          <input
            id="training-benchmark-id"
            value={benchmarkId}
            onChange={(event) => setBenchmarkId(event.target.value)}
            placeholder="mis. snapshot-2026-08-01"
          />

          <label className="training-models-dialog__checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            Saya sudah menyiapkan dataset snapshot ini dan ingin memulai training.
          </label>

          {errorMessage && (
            <p role="alert" className="training-models-dialog__error">
              {errorMessage}
            </p>
          )}

          <div className="training-models-dialog__actions">
            <button
              type="submit"
              className="training-models-btn training-models-btn--primary"
              disabled={!canSubmit || isSubmitting}
            >
              {isSubmitting ? 'Memulai...' : 'Mulai Training'}
            </button>
            <button
              type="button"
              className="training-models-btn"
              onClick={onCancel}
              disabled={isSubmitting}
            >
              Batal
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
