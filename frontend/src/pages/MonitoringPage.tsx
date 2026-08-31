import { Navigate } from 'react-router-dom'

/**
 * `/monitoring` index redirect. Screen-plan's official S-40 path is
 * `/monitoring/live`; `/monitoring` itself has no screen of its own.
 * S-42 Access Log now exists at `/monitoring/events` (FE-11) with its own
 * sidebar nav entry, so this redirect no longer needs revisiting for that
 * reason — it's just a sensible default for whoever lands on the bare
 * `/monitoring` path directly.
 */
export default function MonitoringPage() {
  return <Navigate to="/monitoring/live" replace />
}
