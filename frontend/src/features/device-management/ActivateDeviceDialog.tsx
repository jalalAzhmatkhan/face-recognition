import { useEffect, useRef, useState } from 'react'
import { describeApiError, sendDeviceHeartbeat } from './api'
import type { DeviceStatus } from './types'

interface ActivateDeviceDialogProps {
  deviceId: string
  deviceName: string
  onClose: () => void
}

/** Kept comfortably under the backend's 90s staleness threshold, same
 * constant as `scripts/device_simulator.py::DEFAULT_INTERVAL_SECONDS` — this
 * dialog is the in-browser equivalent of that CLI simulator. */
const HEARTBEAT_INTERVAL_MS = 30_000

type LoopState = 'idle' | 'running' | 'stopped'

/**
 * S-60 device activation: paste a device's credential (shown once at
 * create/rotate time) and send a REAL, CONTINUOUS heartbeat loop against
 * `POST /devices/{id}/heartbeat` — the only code path that sets a device's
 * status to ONLINE — so an operator can bring a dev/test device online from
 * the browser instead of running `scripts/device_simulator.py` from a
 * terminal. Per task instructions this loops (~30s) while the dialog stays
 * open, with an explicit Stop button, rather than sending a single
 * heartbeat and exiting. Unlike `CredentialBootstrapDialog`, this dialog is
 * freely closable at any time (closing just stops the loop; it never
 * displays a credential that must be copied first).
 */
export default function ActivateDeviceDialog({
  deviceId,
  deviceName,
  onClose,
}: ActivateDeviceDialogProps) {
  const [credential, setCredential] = useState('')
  const [loopState, setLoopState] = useState<LoopState>('idle')
  const [lastStatus, setLastStatus] = useState<DeviceStatus | null>(null)
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const [beatCount, setBeatCount] = useState(0)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopLoop() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setLoopState((current) => (current === 'running' ? 'stopped' : current))
  }

  // Loop must stop if the dialog unmounts/closes -- never leave an interval
  // firing against a credential the operator can no longer see or cancel.
  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current)
    }
  }, [])

  async function beat() {
    try {
      const result = await sendDeviceHeartbeat(deviceId, credential.trim())
      setLastStatus(result.status)
      setLastHeartbeatAt(result.last_heartbeat_at)
      setLastError(null)
      setBeatCount((count) => count + 1)
    } catch (error) {
      // A failed beat (bad credential, network blip) never kills the loop
      // silently -- surface it, but keep retrying every interval exactly
      // like the CLI simulator does, in case it's transient.
      setLastError(describeApiError(error))
    }
  }

  function handleStart() {
    if (!credential.trim() || loopState === 'running') return
    setLastError(null)
    setBeatCount(0)
    setLoopState('running')
    void beat()
    intervalRef.current = setInterval(() => {
      void beat()
    }, HEARTBEAT_INTERVAL_MS)
  }

  function handleStop() {
    stopLoop()
  }

  function handleClose() {
    stopLoop()
    onClose()
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
        aria-labelledby="activate-device-dialog-title"
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
        <h2 id="activate-device-dialog-title" style={{ margin: 0, font: 'var(--text-h3)' }}>
          Aktivasi Device: {deviceName}
        </h2>

        <p style={{ margin: 0, color: 'var(--text-secondary)', font: 'var(--text-small)' }}>
          Tempel kredensial device (ditampilkan sekali saat device dibuat/rotasi kredensial) untuk
          mengirim heartbeat berkelanjutan setiap {HEARTBEAT_INTERVAL_MS / 1000} detik, sebagai
          pengganti firmware fisik di lingkungan dev/testing.
        </p>

        <label htmlFor="activate-device-credential" style={{ display: 'none' }}>
          Kredensial Device
        </label>
        <input
          id="activate-device-credential"
          value={credential}
          onChange={(event) => setCredential(event.target.value)}
          disabled={loopState === 'running'}
          placeholder="credential_id.secret"
          style={{
            minHeight: 'var(--touch-target)',
            padding: '0 var(--space-3)',
            borderRadius: 'var(--radius-md)',
            border: 'var(--border-w) solid var(--border-default)',
            fontFamily: 'var(--font-mono)',
          }}
        />

        {loopState === 'running' && (
          <p style={{ margin: 0, color: 'var(--success, var(--accent))', font: 'var(--text-small)' }}>
            Heartbeat berjalan — {beatCount} kali terkirim
            {lastStatus ? `, status terakhir: ${lastStatus}` : ''}
            {lastHeartbeatAt ? ` (${lastHeartbeatAt})` : ''}.
          </p>
        )}
        {loopState === 'stopped' && (
          <p style={{ margin: 0, color: 'var(--text-secondary)', font: 'var(--text-small)' }}>
            Heartbeat dihentikan. {beatCount} kali terkirim sebelum berhenti.
          </p>
        )}
        {lastError && (
          <p role="alert" style={{ margin: 0, color: 'var(--danger)', font: 'var(--text-small)' }}>
            {lastError}
          </p>
        )}

        <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={handleClose}
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-4)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-strong)',
              background: 'var(--bg-surface)',
              cursor: 'pointer',
            }}
          >
            Tutup
          </button>
          {loopState === 'running' ? (
            <button
              type="button"
              onClick={handleStop}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--danger)',
                background: 'var(--danger)',
                color: 'var(--text-inverse)',
                cursor: 'pointer',
              }}
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={handleStart}
              disabled={!credential.trim()}
              style={{
                minHeight: 'var(--touch-target)',
                padding: '0 var(--space-6)',
                borderRadius: 'var(--radius-md)',
                border: 'var(--border-w) solid var(--accent)',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                cursor: credential.trim() ? 'pointer' : 'not-allowed',
                opacity: credential.trim() ? 1 : 0.5,
              }}
            >
              Mulai Heartbeat
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
