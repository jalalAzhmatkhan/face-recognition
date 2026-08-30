import { Navigate } from 'react-router-dom'

/**
 * `/monitoring` index redirect. Screen-plan's official S-40 path is
 * `/monitoring/live`; `/monitoring` itself has no screen of its own (S-42
 * Access Log, which would be the natural "monitoring home", is out of
 * scope for FE-06 and has no task id yet). Redirecting straight to the
 * live feed is the reasonable v1 default rather than a landing page with
 * nothing on it — worth revisiting once S-42 exists.
 */
export default function MonitoringPage() {
  return <Navigate to="/monitoring/live" replace />
}
