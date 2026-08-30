import type { PromotionGateChecks } from './gateChecks'

/** S-52 explicit gate checklist ("Recall >= produksi ✓/✗", "Latency p95 <=
 * 300 ms ✓/✗") — client-side estimate only, see `gateChecks.ts` docstring
 * for why the server's own 409 response is always the final word. */
export default function GateChecklist({ checks }: { checks: PromotionGateChecks }) {
  return (
    <ul className="training-models-gate-list">
      <li
        className={
          checks.recall.passed
            ? 'training-models-gate-item training-models-gate-item--pass'
            : 'training-models-gate-item training-models-gate-item--fail'
        }
      >
        <span className="training-models-gate-item__label">
          Recall ≥ produksi {checks.recall.passed ? '✓' : '✗'}
        </span>
        <p className="training-models-gate-item__note">{checks.recall.note}</p>
      </li>
      <li
        className={
          checks.latency.passed
            ? 'training-models-gate-item training-models-gate-item--pass'
            : 'training-models-gate-item training-models-gate-item--fail'
        }
      >
        <span className="training-models-gate-item__label">
          Latency p95 ≤ 300 ms {checks.latency.passed ? '✓' : '✗'}
        </span>
        <p className="training-models-gate-item__note">{checks.latency.note}</p>
      </li>
    </ul>
  )
}
