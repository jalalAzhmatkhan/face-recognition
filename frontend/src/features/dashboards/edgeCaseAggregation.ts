import type { AccessEventSample, ConditionFlagKey, FunnelBreakdownRow } from './types'
import { CONDITION_FLAG_KEYS, DEVICE_CLASSES, REJECT_STAGES } from './types'

function pct(count: number, total: number): number {
  return total > 0 ? Math.round((count / total) * 1000) / 10 : 0
}

/**
 * Reject-stage breakdown (EC-FE-01, TSD-edge-cases.md D-1): the 5 reject
 * stages plus a synthetic `granted` bucket for `decision === 'GRANTED'`
 * rows (which never carry a `reject_stage`). Rows with `decision !==
 * 'GRANTED'` and no `reject_stage` (e.g. events reported by a pre-EC-BE-01
 * caller) are silently excluded from both the numerator and denominator —
 * they simply predate this funnel and would otherwise skew every
 * percentage downward for no useful reason.
 */
export function computeRejectStageBreakdown(events: AccessEventSample[]): FunnelBreakdownRow[] {
  const granted = events.filter((e) => e.decision === 'GRANTED').length
  const staged = events.filter((e) => e.decision !== 'GRANTED' && e.reject_stage !== null)
  const total = granted + staged.length

  const rows: FunnelBreakdownRow[] = [{ key: 'granted', count: granted, pct: pct(granted, total) }]
  for (const stage of REJECT_STAGES) {
    const count = staged.filter((e) => e.reject_stage === stage).length
    rows.push({ key: stage, count, pct: pct(count, total) })
  }
  return rows
}

/**
 * Condition-flag breakdown: for each canonical flag key, how many events in
 * the sample carry it `true` on `condition_flags`. Percentages are of the
 * WHOLE sample (not just rejects) since a flag can also be present on a
 * GRANTED decision (e.g. `masked` with a matching masked template). A
 * single event can set multiple flags, so these rows do not sum to 100%.
 */
export function computeConditionFlagBreakdown(events: AccessEventSample[]): FunnelBreakdownRow[] {
  const total = events.length
  return CONDITION_FLAG_KEYS.map((key: ConditionFlagKey) => {
    const count = events.filter((e) => e.condition_flags?.[key] === true).length
    return { key, count, pct: pct(count, total) }
  })
}

/**
 * Device-class breakdown of the same sample — `null`/missing (events
 * reported before EC-BE-01, or by a device never classified) is folded
 * into `unknown` rather than dropped, so the percentages still sum to 100%.
 */
export function computeDeviceClassBreakdown(events: AccessEventSample[]): FunnelBreakdownRow[] {
  const total = events.length
  return DEVICE_CLASSES.map((deviceClass) => {
    const count = events.filter(
      (e) => (e.device_class ?? 'unknown') === deviceClass,
    ).length
    return { key: deviceClass, count, pct: pct(count, total) }
  })
}
