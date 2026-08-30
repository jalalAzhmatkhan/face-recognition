import { useState } from 'react'

interface CredentialBootstrapDialogProps {
  /** Device name, for context in the dialog copy. */
  deviceName: string
  /** The one-time bootstrap credential, from `POST /devices` or
   * `POST /devices/{id}/rotate-credential`. */
  credential: string
  /** Called ONLY by the explicit "Saya sudah menyimpan kredensial ini"
   * button below — per task instructions this dialog must NOT be closable
   * by click-outside or ESC, so an operator can't dismiss it before
   * copying the credential down. There is deliberately no `onClose`/overlay
   * click handler and no keydown listener here. */
  onAcknowledge: () => void
}

/**
 * Shown once, right after a device is created or its credential rotated.
 * The backend never returns this value again (BE-09 contract) — the whole
 * point of this dialog is to force the operator to see and copy it now.
 */
export default function CredentialBootstrapDialog({
  deviceName,
  credential,
  onAcknowledge,
}: CredentialBootstrapDialogProps) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'unavailable'>('idle')

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard) {
        setCopyState('unavailable')
        return
      }
      await navigator.clipboard.writeText(credential)
      setCopyState('copied')
    } catch {
      // Clipboard API can throw (permission denied, insecure context, etc.)
      // — never let a copy failure crash the dialog, just tell the operator
      // to copy it manually instead.
      setCopyState('unavailable')
    }
  }

  return (
    <div
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="credential-dialog-title"
        style={{
          background: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-md)',
          padding: 'var(--space-6)',
          maxWidth: 480,
          width: '90%',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <h2 id="credential-dialog-title" style={{ margin: 0, font: 'var(--text-h3)' }}>
          Kredensial Device: {deviceName}
        </h2>

        <p role="alert" style={{ margin: 0, color: 'var(--danger)', font: 'var(--text-small)' }}>
          Kredensial ini HANYA ditampilkan sekali dan tidak akan bisa dilihat lagi setelah
          dialog ini ditutup. Simpan/salin sekarang ke device fisik sebelum melanjutkan.
        </p>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            background: 'var(--bg-sunken)',
            border: 'var(--border-w) solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-3)',
          }}
        >
          <code
            data-testid="credential-value"
            style={{
              flex: 1,
              fontFamily: 'var(--font-mono)',
              wordBreak: 'break-all',
              userSelect: 'all',
            }}
          >
            {credential}
          </code>
          <button
            type="button"
            onClick={handleCopy}
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-4)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-strong)',
              background: 'var(--bg-surface)',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {copyState === 'copied' ? 'Tersalin!' : 'Salin'}
          </button>
        </div>

        {copyState === 'unavailable' && (
          <p style={{ margin: 0, color: 'var(--text-secondary)', font: 'var(--text-caption)' }}>
            Copy otomatis tidak tersedia di browser ini. Silakan blok/salin teks di atas secara
            manual.
          </p>
        )}

        <button
          type="button"
          onClick={onAcknowledge}
          style={{
            minHeight: 'var(--touch-target)',
            padding: '0 var(--space-6)',
            borderRadius: 'var(--radius-md)',
            border: 'var(--border-w) solid var(--accent)',
            background: 'var(--accent)',
            color: 'var(--text-inverse)',
            cursor: 'pointer',
            alignSelf: 'flex-end',
          }}
        >
          Saya sudah menyimpan kredensial ini
        </button>
      </div>
    </div>
  )
}
