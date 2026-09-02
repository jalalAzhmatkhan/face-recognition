/**
 * Bounded-concurrency runner for the sweep-frame uploads.
 *
 * Exists as its own module because the enrollment upload went from 2
 * objects (photo + video) to ~37 (photo + 12 positions x BURST_SIZE), which
 * changes what a partial failure costs. Re-running the whole batch on
 * "Coba Lagi" would mint a fresh presigned key and a fresh PENDING
 * `media_objects` row for every frame that ALREADY landed, leaving
 * duplicate objects in S3 for QC to sift through. So this reports exactly
 * which items are still outstanding, and the caller retries only those.
 */

export interface ConcurrentRunResult<T> {
  /** Items that did not complete — the exact retry list. Empty on success. */
  pending: T[]
  /** The first failure observed, or `null` if everything completed. */
  error: unknown
}

/**
 * Run `task` over `items` with at most `concurrency` in flight.
 *
 * Never throws: a failure is reported via the result instead, because the
 * caller needs the succeeded/pending split more than it needs a stack
 * unwind. After the first failure no further items are STARTED, but tasks
 * already in flight are awaited to completion — abandoning them would
 * leave uploads racing against the UI state that describes them.
 *
 * `onItemDone` fires once per successful item, for progress display.
 */
export async function runConcurrent<T>(
  items: readonly T[],
  concurrency: number,
  task: (item: T) => Promise<void>,
  onItemDone?: () => void,
): Promise<ConcurrentRunResult<T>> {
  const succeeded = new Set<number>()
  let firstError: unknown = null
  let cursor = 0

  const worker = async (): Promise<void> => {
    while (cursor < items.length && firstError === null) {
      const index = cursor
      cursor += 1
      try {
        await task(items[index])
        succeeded.add(index)
        onItemDone?.()
      } catch (error) {
        // Record only the FIRST failure: later ones are usually the same
        // outage observed by a sibling worker, and surfacing the first is
        // what the user can act on.
        if (firstError === null) firstError = error
      }
    }
  }

  const workerCount = Math.max(1, Math.min(concurrency, items.length))
  await Promise.all(Array.from({ length: workerCount }, worker))

  return {
    pending: items.filter((_item, index) => !succeeded.has(index)),
    error: firstError,
  }
}
