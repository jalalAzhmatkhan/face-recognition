/**
 * Humanizes machine-readable QC rejection reasons (FR-ENR-06) into
 * Bahasa Indonesia for the enrollment detail screen (FE-05).
 *
 * The reason vocabulary comes from two places in `ai-training/`:
 *  - session-level (whole video unusable), from
 *    `ai_training/worker/tasks.py`: "video_missing", "video_undecodable".
 *  - per-clock-position, from
 *    `ai_training/quality/pipeline.py::_evaluate_frame` /
 *    `run_quality_check`: "blurry", "bad_lighting", "face_too_small",
 *    "pose_out_of_range", "no_face_detected".
 *
 * Kept as a single lookup table + graceful fallback so a new reason added
 * on the AI/backend side never breaks the UI — it just shows an untranslated
 * fallback message until this table is extended.
 */

export const REASON_TRANSLATIONS: Record<string, string> = {
  // Session-level (no per-position breakdown exists for these).
  video_missing: 'Video tidak ditemukan, silakan rekam ulang.',
  video_undecodable: 'Video rusak/tidak bisa dibaca, silakan rekam ulang.',

  // Per-clock-position.
  blurry:
    'Gambar buram pada posisi ini, silakan rekam ulang dengan pencahayaan dan kestabilan kamera yang lebih baik.',
  bad_lighting:
    'Pencahayaan kurang baik (terlalu gelap atau terlalu terang) pada posisi ini, silakan rekam ulang di tempat dengan pencahayaan yang lebih merata.',
  face_too_small:
    'Wajah terlalu kecil/jauh dari kamera pada posisi ini, silakan dekatkan wajah ke kamera.',
  pose_out_of_range:
    'Arah wajah tidak sesuai target posisi jam ini, silakan ikuti panduan arah kepala dengan lebih tepat.',
  no_face_detected:
    'Wajah tidak terdeteksi pada posisi ini, pastikan wajah selalu terlihat jelas oleh kamera.',
}

/** Fallback for any reason code not yet in `REASON_TRANSLATIONS`. Never
 * throws and never returns an empty string, so an unknown code from a
 * newer QC pipeline version still shows something actionable. */
export function humanizeReason(reason: string): string {
  const translation = REASON_TRANSLATIONS[reason]
  if (translation) return translation
  const label = reason.trim() || 'tidak diketahui'
  return `Alasan penolakan tidak dikenal ("${label}"). Silakan hubungi admin/tim QA jika masalah ini berulang.`
}

export function humanizeReasons(reasons: string[] | null | undefined): string[] {
  if (!reasons || reasons.length === 0) return []
  return reasons.map(humanizeReason)
}
