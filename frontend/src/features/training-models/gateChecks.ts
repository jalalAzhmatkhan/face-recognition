import type { ModelVersionResponse } from './types'

/**
 * Pure client-side re-implementation of FR-TRN-05's two data-driven
 * promotion gates (`backend/app/services/training_service.py::
 * promote_model`'s recall-no-regression and latency-budget checks), used
 * for instant UI feedback on S-52 BEFORE the operator submits.
 *
 * The server is ALWAYS the final source of truth: `ModelPromotionPage`
 * calls `POST /models/{version}/promote` regardless of what this module
 * says, and shows the server's own 409 `reasons` verbatim if it disagrees
 * (e.g. because the underlying data changed between page load and submit,
 * or because of the two gates NOT modeled here — `confirm=true` and
 * CANDIDATE-only stage, which the page/dialog already enforce structurally
 * instead).
 */

/** Mirrors `Settings.promotion_latency_budget_ms` default
 * (`backend/app/core/config.py`) — NFR-PRF-01. The server's actual
 * configured value could differ; this is only for the client-side estimate. */
export const LATENCY_BUDGET_MS = 300

export type MetricDirection = 'up' | 'down' | 'flat' | 'unknown'

export interface MetricDelta {
  candidate: number | null
  production: number | null
  direction: MetricDirection
}

/** Delta direction for a "higher is better" metric (recall/f1/precision).
 * `unknown` when either side is missing — e.g. no production baseline yet —
 * so callers don't render a misleading arrow. */
export function compareHigherIsBetter(
  candidate: number | null,
  production: number | null,
): MetricDelta {
  if (candidate === null || production === null) {
    return { candidate, production, direction: 'unknown' }
  }
  if (candidate > production) return { candidate, production, direction: 'up' }
  if (candidate < production) return { candidate, production, direction: 'down' }
  return { candidate, production, direction: 'flat' }
}

/** Delta direction for a "lower is better" metric (latency): candidate
 * being LOWER is the "up"/green/improvement direction. */
export function compareLowerIsBetter(
  candidate: number | null,
  production: number | null,
): MetricDelta {
  if (candidate === null || production === null) {
    return { candidate, production, direction: 'unknown' }
  }
  if (candidate < production) return { candidate, production, direction: 'up' }
  if (candidate > production) return { candidate, production, direction: 'down' }
  return { candidate, production, direction: 'flat' }
}

export interface GateCheck {
  passed: boolean
  note: string
}

export interface PromotionGateChecks {
  recall: GateCheck
  latency: GateCheck
  allPassed: boolean
}

function formatMetric(value: number | null): string {
  return value === null ? 'tidak diketahui' : value.toFixed(4)
}

/**
 * Mirrors the two metric-comparison gates from `promote_model` (recall
 * no-regression + latency budget). The other two gates there (`confirm`
 * must be explicitly true, and the model must be stage CANDIDATE) are not
 * metric comparisons — they're enforced structurally elsewhere (the confirm
 * dialog, and "Review" only ever linking here for CANDIDATE rows).
 */
export function computePromotionGateChecks(
  candidate: ModelVersionResponse,
  production: ModelVersionResponse | null,
): PromotionGateChecks {
  let recall: GateCheck
  if (production === null) {
    recall = {
      passed: true,
      note: 'Promosi pertama — tidak ada baseline produksi untuk dibandingkan.',
    }
  } else {
    const candidateRecall = candidate.recall ?? -1
    const productionRecall = production.recall ?? 0
    const passed = candidateRecall >= productionRecall
    recall = {
      passed,
      note: passed
        ? `Recall kandidat (${formatMetric(candidate.recall)}) >= produksi (${formatMetric(production.recall)}).`
        : `Recall kandidat (${formatMetric(candidate.recall)}) di bawah produksi (${formatMetric(production.recall)}) — akan ditolak server.`,
    }
  }

  const latency = candidate.latency_ms_p95
  const latencyPassed = latency !== null && latency <= LATENCY_BUDGET_MS
  const latencyCheck: GateCheck = {
    passed: latencyPassed,
    note: latencyPassed
      ? `Latency p95 kandidat ${latency}ms <= budget ${LATENCY_BUDGET_MS}ms.`
      : `Latency p95 kandidat ${latency ?? 'tidak diketahui'}ms melebihi budget ${LATENCY_BUDGET_MS}ms — akan ditolak server.`,
  }

  return { recall, latency: latencyCheck, allPassed: recall.passed && latencyCheck.passed }
}
