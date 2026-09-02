import { describe, expect, it, vi } from 'vitest'
import { runConcurrent } from './uploadQueue'

const items = (n: number) => Array.from({ length: n }, (_, i) => i)

describe('runConcurrent', () => {
  it('runs every item and reports nothing pending on success', async () => {
    const seen: number[] = []
    const result = await runConcurrent(items(10), 3, async (item) => {
      seen.push(item)
    })

    expect(seen.sort((a, b) => a - b)).toEqual(items(10))
    expect(result).toEqual({ pending: [], error: null })
  })

  it('never exceeds the concurrency limit', async () => {
    let inFlight = 0
    let peak = 0
    await runConcurrent(items(20), 4, async () => {
      inFlight += 1
      peak = Math.max(peak, inFlight)
      await Promise.resolve()
      await Promise.resolve()
      inFlight -= 1
    })

    expect(peak).toBeLessThanOrEqual(4)
    expect(peak).toBeGreaterThan(1)
  })

  it('returns only the items that did not complete', async () => {
    // Serial (concurrency 1) so the failure point is exact: 0 and 1 land,
    // 2 fails, and nothing after it is even started.
    const result = await runConcurrent(items(5), 1, async (item) => {
      if (item === 2) throw new Error('boom')
    })

    expect(result.pending).toEqual([2, 3, 4])
    expect((result.error as Error).message).toBe('boom')
  })

  it('does not re-run items that already succeeded when the caller retries', async () => {
    // This IS the reason the module exists: a retry that re-uploaded
    // already-landed frames would leave duplicate S3 objects and duplicate
    // PENDING media_objects rows behind.
    const attempts = new Map<number, number>()
    const flaky = async (item: number) => {
      const count = (attempts.get(item) ?? 0) + 1
      attempts.set(item, count)
      if (item === 3 && count === 1) throw new Error('transient')
    }

    const first = await runConcurrent(items(6), 1, flaky)
    expect(first.pending).toEqual([3, 4, 5])

    const second = await runConcurrent(first.pending, 1, flaky)
    expect(second).toEqual({ pending: [], error: null })

    expect(attempts.get(0)).toBe(1)
    expect(attempts.get(1)).toBe(1)
    expect(attempts.get(2)).toBe(1)
    expect(attempts.get(3)).toBe(2)
  })

  it('stops starting new items after the first failure', async () => {
    const started: number[] = []
    await runConcurrent(items(50), 2, async (item) => {
      started.push(item)
      if (item === 0) throw new Error('boom')
    })

    // The sibling worker's in-flight item may still land, but the queue
    // must not drain all 50 against a server that is clearly failing.
    expect(started.length).toBeLessThan(10)
  })

  it('awaits in-flight tasks rather than abandoning them mid-upload', async () => {
    let slowFinished = false
    const result = await runConcurrent([0, 1], 2, async (item) => {
      if (item === 0) throw new Error('fast failure')
      await new Promise((resolve) => setTimeout(resolve, 5))
      slowFinished = true
    })

    expect(slowFinished).toBe(true)
    expect(result.pending).toEqual([0])
  })

  it('reports the FIRST failure when several workers fail', async () => {
    const result = await runConcurrent([0, 1, 2], 1, async (item) => {
      throw new Error(`fail-${item}`)
    })
    expect((result.error as Error).message).toBe('fail-0')
  })

  it('fires the progress callback once per successful item only', async () => {
    const onItemDone = vi.fn()
    await runConcurrent(items(5), 1, async (item) => {
      if (item === 3) throw new Error('boom')
    }, onItemDone)

    expect(onItemDone).toHaveBeenCalledTimes(3)
  })

  it('handles an empty list without spawning a worker', async () => {
    const task = vi.fn()
    const result = await runConcurrent([], 4, task)

    expect(task).not.toHaveBeenCalled()
    expect(result).toEqual({ pending: [], error: null })
  })
})
