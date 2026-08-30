import { useState } from 'react'

interface PromoteConfirmDialogProps {
  candidateVersion: string
  productionVersion: string | null
  isSubmitting: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * S-52 confirmation dialog shown right before `POST /models/{version}/
 * promote {confirm: true}`. Mirrors `device-management/
 * CredentialBootstrapDialog`'s pattern of an explicit acknowledge gate
 * (here: a checkbox, since there is nothing to copy) rather than an
 * always-enabled action button — promotion retires the current production
 * model and FR-TRN-05 requires this to be human-in-the-loop, so a stray
 * click on "Promote" must never be enough on its own.
 *
 * Per FE-09 task instructions this dialog is honest that gallery
 * re-embedding (TR-08, FR-TRN-06) is NOT triggered automatically — it does
 * not show a fake re-embed progress step, before or after confirming.
 */
export default function PromoteConfirmDialog({
  candidateVersion,
  productionVersion,
  isSubmitting,
  onConfirm,
  onCancel,
}: PromoteConfirmDialogProps) {
  const [acknowledged, setAcknowledged] = useState(false)

  return (
    <div role="presentation" className="training-models-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="promote-confirm-title"
        className="training-models-dialog"
      >
        <h2 id="promote-confirm-title" className="training-models-dialog__title">
          Promosikan {candidateVersion} ke Produksi?
        </h2>
        <ul className="training-models-dialog__notes">
          <li>
            Versi <strong>{candidateVersion}</strong> akan menjadi model PRODUCTION.
          </li>
          <li>
            {productionVersion
              ? `Versi produksi saat ini (${productionVersion}) akan otomatis di-retire.`
              : 'Belum ada model produksi sebelumnya — ini adalah promosi pertama.'}
          </li>
          <li className="training-models-dialog__notes-warning">
            Re-embedding gallery (blue/green switch) BELUM otomatis dijalankan setelah promosi ini
            (TR-08 belum diimplementasikan) — perlu tindakan manual terpisah agar gallery memakai
            model baru.
          </li>
        </ul>

        <label className="training-models-dialog__checkbox">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          Saya memahami konsekuensi di atas dan ingin melanjutkan promosi.
        </label>

        <div className="training-models-dialog__actions">
          <button type="button" disabled={!acknowledged || isSubmitting} onClick={onConfirm}>
            {isSubmitting ? 'Memproses...' : 'Promote ke Produksi'}
          </button>
          <button type="button" onClick={onCancel} disabled={isSubmitting}>
            Batal
          </button>
        </div>
      </div>
    </div>
  )
}
