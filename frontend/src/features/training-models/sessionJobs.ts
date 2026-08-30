import type { SessionTrainingJob } from './types'

/**
 * Browser-local record of training jobs triggered from THIS browser session.
 *
 * GAP (documented per FE-09 task instructions — flag as a candidate backend
 * follow-up, e.g. "BE-15: GET /training/jobs list endpoint"): BE-13
 * (`backend/app/routers/training.py`) only exposes `GET /training/jobs/{id}`
 * — a single job by id — with NO `GET /training/jobs` list endpoint. There
 * is therefore no way to fetch a full server-side history of training runs
 * at all.
 *
 * S-50's "tabel training runs" is rebuilt here as a list of jobs THIS
 * browser itself triggered (id + submitted params), persisted to
 * `localStorage` so it survives a reload, and polled individually via
 * `GET /training/jobs/{id}` for status. The UI using this module MUST label
 * it honestly as "job yang dipicu di sesi ini" — never as a complete
 * server-side history, since a different browser/session/device triggering
 * a job would never show up here.
 */

const STORAGE_KEY = 'frac_training_jobs_session'

function readRaw(): unknown {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function isSessionTrainingJob(value: unknown): value is SessionTrainingJob {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.model_version === 'string' &&
    typeof candidate.benchmark_id === 'string' &&
    typeof candidate.created_at === 'string'
  )
}

/** Returns jobs newest-first. Malformed entries (corrupted or hand-edited
 * localStorage) are silently dropped rather than thrown — a bad stored
 * value should never break the page. */
export function listSessionTrainingJobs(): SessionTrainingJob[] {
  const raw = readRaw()
  if (!Array.isArray(raw)) return []
  return raw
    .filter(isSessionTrainingJob)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

/** Adds (or replaces, if the id already exists) one session job entry. */
export function addSessionTrainingJob(job: SessionTrainingJob): void {
  const existing = listSessionTrainingJobs()
  const next = [job, ...existing.filter((existingJob) => existingJob.id !== job.id)]
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    /* localStorage unavailable (private mode) — job just won't persist across reload */
  }
}
